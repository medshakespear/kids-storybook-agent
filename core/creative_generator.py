"""Let the language model author activity concepts and layouts, not fill fixed worksheets."""
from __future__ import annotations

import json
import logging
import random
import re
import time
from copy import deepcopy
from html.parser import HTMLParser
from uuid import uuid4

from core.activity_generator import ActivityGenerationError, _text
from core.creative_layout import check_page, preflight_pack, PROPERTIES, TAGS, reveal_print_content
from core.image_generator import generate_images
from core.task_visuals import VISUAL_CONTRACT, BOUND_VISUAL_CONTRACT, page_visuals, normalize_visual_metadata, SHAPES, COLORS
from core.exercise_quality import validate_exercises, proofread_pack, activity_title
from core.providers import text_provider_names, text_client, text_worker_limit, safe_api_error
from core.runtime import int_setting, ordered_parallel
from core.page_contract import compile_exercise, validate_brief, EXERCISE_CONTRACT

LOGGER = logging.getLogger(__name__)


def parse_design_json(content: str) -> dict:
    """Decode one design, allowing fences or identical echoes but never conflicting data."""
    value = content.strip()
    if value.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```', value, re.I)
        if match:
            value = match[1]
    try:
        result = json.loads(value)
    except json.JSONDecodeError as original_error:
        if original_error.msg != 'Extra data':
            raise
        decoder = json.JSONDecoder()
        result, end = decoder.raw_decode(value)
        remainder = value[end:].strip()
        # Some compatible endpoints append a closing fence or echo the same object.
        # Never discard prose, new fields or a different second design.
        while remainder and remainder != '```':
            try:
                duplicate, end = decoder.raw_decode(remainder)
            except json.JSONDecodeError:
                raise original_error from None
            if json.dumps(duplicate,sort_keys=True) != json.dumps(result,sort_keys=True):
                raise ValueError('Response contains conflicting JSON objects; return exactly one complete object')
            remainder = remainder[end:].strip()
    if not isinstance(result, dict):
        raise ValueError('Design response must be one JSON object')
    return result


def merge_answer_repair(original: dict, correction: dict, question_id: str, *, calculation: bool = False) -> dict:
    """Apply one bounded-answer correction without letting a retry replace artwork or tasks."""
    exercise = correction.get('exercise') if isinstance(correction,dict) else None
    questions = exercise.get('questions') if isinstance(exercise,dict) else None
    matches = [q for q in questions if isinstance(q,dict) and str(q.get('id'))==question_id] if isinstance(questions,list) else []
    if len(matches)!=1 or 'answer' not in matches[0]:
        raise ValueError(f'Answer-only repair must supply one exercise.questions answer for id {question_id}; preserve its ID')
    result = deepcopy(original)
    targets = [q for q in result['exercise']['questions'] if isinstance(q,dict) and str(q.get('id'))==question_id]
    if len(targets)!=1:
        raise ValueError('Answer-only repair requires an unambiguous original question ID')
    targets[0]['answer'] = deepcopy(matches[0]['answer'])
    if calculation:
        if 'calculation' in matches[0]: targets[0]['calculation'] = deepcopy(matches[0]['calculation'])
        else: targets[0].pop('calculation',None)
    return result


def repair_printed_arithmetic(page: dict, question_id: str) -> dict | None:
    """Compute a standalone printed expression; leave word problems for semantic repair."""
    from core.exercise_quality import calculate, normalize_calculation, numeric_display_text
    from fractions import Fraction
    exercise = page.get('exercise') if isinstance(page,dict) else None
    questions = exercise.get('questions') if isinstance(exercise,dict) else None
    matches = [q for q in questions if isinstance(q,dict) and str(q.get('id'))==question_id] if isinstance(questions,list) else []
    if len(matches)!=1:
        return None
    question = matches[0]
    prompt = numeric_display_text(str(question.get('prompt','')))
    match = re.fullmatch(r'\s*(?:(?:what is|calculate|solve|evaluate|find the value of)\s+)?'
                         r'([\d.()+−×÷*/\s-]+)\s*[?=]?\s*',prompt,re.I)
    answer = str(question.get('answer','')).strip()
    if not match or not re.fullmatch(r'-?(?:\d+(?:\.\d+)?|\.\d+)(?:/\d+)?',answer):
        return None
    calculation = question.get('calculation')
    if not isinstance(calculation,dict):
        return None
    try:
        printed = normalize_calculation(match[1])
        expression = normalize_calculation(calculation.get('expression'))
        actual = calculate(printed)
        if calculate(expression)!=actual:
            return None
        supplied = Fraction(str(calculation.get('answer')))
        keyed = Fraction(answer)
    except (ValueError,TypeError,ZeroDivisionError):
        return None
    if supplied==actual and keyed==actual:
        return None
    result = deepcopy(page)
    target = next(q for q in result['exercise']['questions'] if str(q.get('id'))==question_id)
    # Fractions keep nonterminating division exact; the shared validator accepts them.
    target['calculation'] = {'expression':expression,'answer':str(actual)}
    target['answer'] = str(actual)
    return result


def merge_prompt_repair(original: dict, correction: dict, question_id: str) -> dict:
    """Shorten only one task prompt while retaining its numbers, answer, artwork and space."""
    from core.prompt_recovery import numeric_values
    from core.exercise_quality import rounding_precision
    questions = correction.get('exercise',{}).get('questions') if isinstance(correction,dict) and isinstance(correction.get('exercise'),dict) else None
    matches = [q for q in questions if isinstance(q,dict) and str(q.get('id'))==question_id] if isinstance(questions,list) else []
    targets = [q for q in original['exercise']['questions'] if isinstance(q,dict) and str(q.get('id'))==question_id]
    if len(matches)!=1 or len(targets)!=1 or not isinstance(matches[0].get('prompt'),str):
        raise ValueError(f'Prompt-only repair must supply one exercise.questions prompt for id {question_id}')
    new = matches[0]['prompt'].strip()
    old = targets[0].get('prompt')
    if isinstance(old,str) and numeric_values(old)!=numeric_values(new):
        raise ValueError(f'Prompt-only repair for question {question_id} must preserve every numeric value and quantity')
    if isinstance(old,str) and rounding_precision(old)!=rounding_precision(new):
        raise ValueError(f'Prompt-only repair for question {question_id} must preserve the printed rounding precision')
    result = deepcopy(original)
    next(q for q in result['exercise']['questions'] if str(q.get('id'))==question_id)['prompt'] = new
    return result


def exact_wording_requires_content_repair(page: dict, error: str) -> bool:
    """Treat exact-puzzle instruction conflicts as content defects, not decorative captions."""
    exercise = page.get('exercise') if isinstance(page,dict) else None
    if not isinstance(exercise,dict) or exercise.get('render_mode')!='exact':
        return False
    return error.startswith(('Put ALL printed wording', 'Exact captions must not contain task directions')) or (
        error.startswith('Unknown or repeated exercise content slot:') and
        any(f'content slot: {slot};' in error for slot in ('directions','passage')))


def merge_exact_wording_repair(original: dict, correction: dict) -> dict:
    """Accept corrected wording bindings while pinning the existing puzzle and valid actions."""
    if not isinstance(correction,dict) or not isinstance(correction.get('exercise'),dict):
        raise ValueError('Exact wording repair must return a complete shared exercise and HTML')
    result = deepcopy(correction)
    retained = original['exercise']
    exercise = result['exercise']
    for key in ('render_mode','mechanic','goal','visual','mechanic_constraints'):
        if key in retained:
            exercise[key] = deepcopy(retained[key])
        else:
            exercise.pop(key,None)
    reserved = str(retained.get('visual',{}).get('question'))
    old_questions = retained.get('questions',[])
    new_questions = exercise.get('questions',[])
    if not isinstance(old_questions,list) or not isinstance(new_questions,list):
        raise ValueError('Exact wording repair must retain canonical questions as a list')
    for question in old_questions:
        if isinstance(question,dict) and str(question.get('id'))!=reserved:
            matches = [q for q in new_questions if isinstance(q,dict) and str(q.get('id'))==str(question.get('id'))]
            if len(matches)!=1 or matches[0]!=question:
                raise ValueError('Exact wording repair must preserve existing additional questions, answers and response space')
    result['images'] = deepcopy(original.get('images',[]))
    return result


def merge_layout_repair(original: dict, correction: dict) -> dict:
    """Retain task data while binding previously printed contextual headings as captions."""
    from core.content_binding import CanonicalTextContainers, CONTAINERS
    if not isinstance(correction,dict) or not isinstance(correction.get('html'),str):
        raise ValueError('Layout-only repair must return a complete html fragment')
    result = deepcopy(original)
    result['html'] = correction['html']
    supplied = correction.get('exercise',{}).get('captions',[]) if isinstance(correction.get('exercise'),dict) else []
    if not isinstance(supplied,list):
        raise ValueError('Layout caption recovery must supply captions as a list')
    if not supplied:
        return result
    parser = CanonicalTextContainers({})
    parser.feed(original['html']);parser.close()
    if parser.stack:
        raise ValueError('Exercise layout tags must be balanced')
    words = set()
    declared_slots = {'caption_'+c['id'] for c in original['exercise'].get('captions',[])
                      if isinstance(c,dict) and isinstance(c.get('id'),str)}
    def normalized(text):
        """Compare complete labels independent of whitespace and case."""
        return ' '.join(text.split()).casefold()
    def collect(node):
        """Read complete text-only containers without taking words from artwork or slots."""
        if isinstance(node,str) or 'comment' in node:
            return
        slot = dict(node['attrs']).get('data-content')
        if node['tag'] in CONTAINERS and (not slot or (slot.startswith('caption_') and slot not in declared_slots)):
            pieces = [parser.plain_text(c) for c in node['children']]
            if all(p is not None for p in pieces):
                words.add(normalized(''.join(pieces)))
        for child in node['children']:
            collect(child)
    for node in parser.root:
        collect(node)
    captions = deepcopy(result['exercise'].get('captions',[]))
    if not isinstance(captions,list):
        raise ValueError('Exercise captions must be a list')
    by_id = {c['id']:c for c in captions if isinstance(c,dict) and isinstance(c.get('id'),str)}
    for caption in supplied:
        if not isinstance(caption,dict) or not isinstance(caption.get('id'),str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,23}',caption['id']):
            raise ValueError('Layout caption recovery needs a short lowercase caption id')
        cid,text = caption['id'],caption.get('text')
        if cid in by_id:
            if text!=by_id[cid].get('text'):
                raise ValueError('Layout-only repair cannot change existing caption wording')
            continue
        if not isinstance(text,str) or not text.strip() or len(text.strip())>120:
            raise ValueError('Layout caption recovery needs nonempty original label text <=120 characters')
        equivalent = next((c['id'] for c in captions if normalized(str(c.get('text','')))==normalized(text)),None)
        if equivalent:
            result['html'] = re.sub(r'''(\bdata-content\s*=\s*)(["'])caption_'''+re.escape(cid)+r'''\2''',
                                    lambda m:m[1]+m[2]+'caption_'+equivalent+m[2],result['html'])
            continue
        if normalized(text) not in words:
            raise ValueError('Layout-only repair may add captions only for complete wording already printed in the retained page')
        if len(captions)>=6:
            raise ValueError('Exercise captions must be a list of at most six short contextual labels')
        captions.append({'id':cid,'text':text.strip()})
        by_id[cid] = captions[-1]
    if captions:
        result['exercise']['captions'] = captions
    return result


def merge_plan_mode_repair(original: dict, correction: dict, page_number: int) -> dict:
    """Repair one planned mode without replacing concepts, titles or art direction."""
    pages = correction.get('pages') if isinstance(correction,dict) else None
    matches = [p for p in pages if isinstance(p,dict) and type(p.get('page_number')) is int
               and p['page_number']==page_number] if isinstance(pages,list) else []
    if len(matches)!=1 or matches[0].get('render_mode') not in {'exact','authored'}:
        raise ValueError(f'Plan mode repair must return one page_number {page_number} with render_mode exact or authored')
    if not 1<=page_number<=len(original['pages']):
        raise ValueError('Plan mode repair page number is outside the retained plan')
    result = deepcopy(original)
    result['pages'][page_number-1]['render_mode'] = matches[0]['render_mode']
    return result


def merge_plan_constraints_repair(original: dict, correction: dict, page_number: int) -> dict:
    """Apply and validate only one page's options, retaining all curriculum and tool choices."""
    pages = correction.get('pages') if isinstance(correction,dict) else None
    matches = [p for p in pages if isinstance(p,dict) and type(p.get('page_number')) is int
               and p['page_number']==page_number] if isinstance(pages,list) else []
    if len(matches)!=1 or not isinstance(matches[0].get('mechanic_constraints'),dict):
        raise ValueError(f'Plan constraints repair must return one page_number {page_number} with mechanic_constraints object')
    if not 1<=page_number<=len(original['pages']):
        raise ValueError('Plan constraints repair page number is outside the retained plan')
    result = deepcopy(original)
    target = result['pages'][page_number-1]
    target['mechanic_constraints'] = deepcopy(matches[0]['mechanic_constraints'])
    validate_brief(target,planning=True)
    return result


def illustration_references(markup: str) -> list[str]:
    """Read authored image slots without guessing subjects or depending on quoting style."""
    parser = HTMLParser(convert_charrefs=True)
    refs = []
    def visit(tag, attrs):
        """Collect only actual img data-asset references, including unquoted attributes."""
        if tag=='img' and dict(attrs).get('data-asset'):
            refs.append(dict(attrs)['data-asset'])
    parser.handle_starttag = visit
    parser.feed(markup)
    return list(dict.fromkeys(refs))


def merge_manifest_repair(original: dict, correction: dict) -> dict:
    """Recover authored prompts while retaining the original task and existing image layout."""
    images = correction.get('images') if isinstance(correction,dict) else None
    if not isinstance(images,list) or not 1<=len(images)<=4 or any(
            not isinstance(a,dict) or not isinstance(a.get('id'),str) or not a['id'].strip()
            or not isinstance(a.get('prompt'),str) or not a['prompt'].strip() for a in images):
        raise ValueError('Illustration manifest recovery must return images as 1-4 explicit nonempty id/prompt objects; never null')
    result = deepcopy(original)
    result['images'] = deepcopy(images)
    if not illustration_references(original['html']):
        markup = correction.get('html')
        if not isinstance(markup,str) or not markup.strip():
            raise ValueError('Illustration manifest recovery must also add visible image slots when the original HTML has none')
        result['html'] = markup
    return result


def merge_exercise_repair(original: dict, correction: dict) -> dict:
    """Recover missing task data while retaining the page's artwork and layout."""
    exercise = correction.get('exercise') if isinstance(correction,dict) else None
    if not isinstance(exercise,dict) or not exercise:
        raise ValueError('Exercise recovery must return a JSON object under the top-level exercise key; never null or a string')
    result = deepcopy(original)
    result['exercise'] = deepcopy(exercise)
    return result


def ask_json(prompt: str, validate, label: str, tokens: int = 6000, *, response_schema: dict | None = None) -> dict:
    """Retry validation defects separately from transient provider transport failures."""
    errors = []
    answer_repair_base, answer_repair_id = None, None
    repair_calculation = False
    layout_repair_base = None
    manifest_repair_base = None
    exercise_repair_base = None
    exact_repair_base = None
    prompt_repair_base, prompt_repair_id = None, None
    plan_mode_base, plan_mode_number = None, None
    plan_repair_field = "render_mode"
    layout_rescue_attempted = False
    floor_match = re.search(r'Minimum student font: (\d+)pt', prompt)
    minimum_font = int(floor_match[1]) if floor_match else 11
    layout_visual_area = 10500 if minimum_font>=14 else 10000 if minimum_font==13 else 8000 if minimum_font==12 else 6000
    messages = [
        {'role': 'system', 'content': (
            'You are an original elementary curriculum designer and print art director. '
            'Return valid JSON only. Use single quotes for HTML attribute values inside JSON strings; '
            'escape any embedded double quotes and line breaks. No trailing commas or Markdown fences.'
        )},
        {'role': 'user', 'content': prompt},
    ]
    max_validation_attempts = int_setting('DESIGN_VALIDATION_ATTEMPTS', 4, 3, 6)
    progress_allowance = 2
    previous_defect = None
    # A real Gemini 503 incident can last longer than a few seconds. Keep the
    # current sticky key and back off slowly; only 429 quota handling may rotate.
    max_transport_failures = int_setting('GEMINI_TRANSPORT_ATTEMPTS', 8, 3, 12)

    for provider in text_provider_names():
        api, model = text_client(provider)
        try:
            validation_attempt = 0
            transport_failures = 0
            while validation_attempt < max_validation_attempts:
                content = None
                validated_draft = None
                scoped_merge = False
                try:
                    LOGGER.info('%s: %s / %s attempt %s', label, provider, model,
                                validation_attempt + 1)
                    from core.response_schemas import obj, array, enum, text, integer, field_repair_schema, manifest_schema
                    schema = response_schema
                    # Match the schema to exactly the fields this repair is allowed to change.
                    if plan_mode_base is not None:
                        from core.response_schemas import mechanic_constraints_schema
                        field_schema = (mechanic_constraints_schema(plan_mode_base['pages'][plan_mode_number-1]['mechanic'])
                                        if plan_repair_field=='mechanic_constraints' else enum(['authored','exact']))
                        schema = obj({'pages': array(obj({'page_number': integer(plan_mode_number,plan_mode_number),
                                                        plan_repair_field: field_schema}),1,1)})
                    elif exercise_repair_base is not None and response_schema is not None:
                        schema = obj({'exercise': response_schema['properties']['exercise']})
                    elif manifest_repair_base is not None:
                        props = {'images': manifest_schema()}
                        if not illustration_references(manifest_repair_base['html']):
                            props['html'] = text(18000)
                        schema = obj(props)
                    elif prompt_repair_base is not None:
                        schema = field_repair_schema(prompt_repair_id,'prompt')
                    elif answer_repair_base is not None:
                        schema = field_repair_schema(answer_repair_id,'answer',calculation=repair_calculation)
                    elif layout_repair_base is not None:
                        schema = obj({'html':text(18000), 'exercise':obj({'captions':array(
                            obj({'id':text(24),'text':text(120)}),0,6)})},['html'])
                    response_format = ({'type':'json_schema','json_schema':{
                        'name':'activity_response','schema':schema}} if schema is not None and provider=='gemini'
                        else {'type':'json_object'})
                    response = api.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_format=response_format,
                        temperature=0.3 if errors else 0.8,
                        max_completion_tokens=tokens,
                    )
                    content = response.choices[0].message.content
                    if not content:
                        raise ValueError('Empty design response')
                    if getattr(response.choices[0], 'finish_reason', None) == 'length':
                        raise ValueError(
                            'Response was truncated by the token limit; return a shorter complete '
                            'design with concise markup'
                        )
                    draft = parse_design_json(content)
                    if plan_mode_base is not None:
                        merger = merge_plan_constraints_repair if plan_repair_field=='mechanic_constraints' else merge_plan_mode_repair
                        draft = merger(plan_mode_base,draft,plan_mode_number)
                        scoped_merge = True
                    elif exercise_repair_base is not None:
                        draft = merge_exercise_repair(exercise_repair_base,draft)
                        scoped_merge = True
                    elif manifest_repair_base is not None:
                        draft = merge_manifest_repair(manifest_repair_base,draft)
                        scoped_merge = True
                    elif exact_repair_base is not None:
                        draft = merge_exact_wording_repair(exact_repair_base,draft)
                        scoped_merge = True
                    elif prompt_repair_base is not None:
                        draft = merge_prompt_repair(prompt_repair_base,draft,prompt_repair_id)
                        scoped_merge = True
                    elif answer_repair_base is not None:
                        draft = merge_answer_repair(answer_repair_base,draft,answer_repair_id,calculation=repair_calculation)
                        scoped_merge = True
                    elif layout_repair_base is not None:
                        draft = merge_layout_repair(layout_repair_base,draft)
                        scoped_merge = True
                    validated_draft = deepcopy(draft)
                    result = validate(draft)
                    return result
                except (ValueError, TypeError, KeyError, IndexError) as exc:
                    visual_match = re.search(r'Visuals are too small: use at least (\d+) square mm',str(exc))
                    if visual_match:
                        layout_visual_area = int(visual_match[1])
                    rescue_base = layout_repair_base
                    if (rescue_base is None and response_schema is not None and validated_draft is not None
                            and str(exc).startswith(('Design overflow:', 'Design content extends outside printable bounds:', 'Visuals are too small'))):
                        rescue_base = validated_draft
                    if rescue_base is not None and not layout_rescue_attempted:
                        from core.layout_recovery import single_illustration_recovery, single_exact_visual_recovery, multiple_illustration_recovery
                        rescue = single_illustration_recovery(rescue_base,minimum_font,layout_visual_area)
                        if rescue is None:
                            rescue = multiple_illustration_recovery(rescue_base,minimum_font,layout_visual_area)
                        if rescue is None:
                            rescue = single_exact_visual_recovery(rescue_base,minimum_font,layout_visual_area)
                        if rescue is not None:
                            layout_rescue_attempted = True
                            try:
                                recovered = validate(rescue)
                            except (ValueError,TypeError,KeyError,IndexError):
                                pass  # No clipping, hidden wording or smaller response areas.
                            else:
                                LOGGER.info('%s: measured single-visual layout recovery succeeded',label)
                                return recovered
                    locally_repaired = set()
                    while validated_draft is not None:
                        local_math = re.search(r'Question ([1-9]\d?(?:[A-Za-z])?): (?:declared math answer|answer key)',str(exc))
                        if not local_math or local_math[1] in locally_repaired:
                            break
                        corrected = repair_printed_arithmetic(validated_draft,local_math[1])
                        if corrected is None:
                            from core.math_result_recovery import repair_declared_result
                            corrected = repair_declared_result(validated_draft,local_math[1])
                        if corrected is None:
                            break
                        locally_repaired.add(local_math[1])
                        LOGGER.info('%s: computing the declared calculation result and key for question %s locally',label,local_math[1])
                        validated_draft = corrected
                        try:
                            return validate(deepcopy(corrected))
                        except (ValueError,TypeError,KeyError,IndexError) as remaining:
                            exc = remaining
                    validation_attempt += 1
                    # A verified scoped correction exposing a different defect is
                    # progress, not another failure of the same repair. At most two
                    # extra calls per unit; unchanged defects get no extra budget.
                    defect = re.search(r'(Exercise question [1-9]\d?[A-Za-z]? (?:prompt|answer/criterion)|Question [1-9]\d?[A-Za-z]?:)',str(exc))
                    defect = defect[1] if defect else next((k for k in (
                        'Design overflow', 'Design content extends outside printable bounds',
                        'Visuals are too small', 'Illustration manifest', 'Supply 1-4',
                        'Render every purposeful') if str(exc).startswith(k)),str(exc).split(';',1)[0])
                    if scoped_merge and validated_draft is not None and previous_defect is not None and defect!=previous_defect and progress_allowance:
                        validation_attempt -= 1
                        progress_allowance -= 1
                        LOGGER.info('%s: scoped repair succeeded; allowing repair of the next independent defect',label)
                    previous_defect = defect
                    transport_failures = 0
                    reason = f'{label}: {provider}: {exc}'
                    errors.append(reason)
                    LOGGER.warning('%s', reason)
                    if validation_attempt >= max_validation_attempts:
                        break

                    # Answer-length repairs cannot remove illustrations or replace the original task.
                    answer_match = re.search(r'Exercise question ([1-9]\d?(?:[A-Za-z])?) answer/criterion',str(exc))
                    prompt_match = re.search(r'Exercise question ([1-9]\d?(?:[A-Za-z])?) prompt must',str(exc))
                    math_match = re.search(r'Question ([1-9]\d?(?:[A-Za-z])?): (?:declared math answer|calculation expression|answer key|calculation does not solve|printed arithmetic)',str(exc))
                    if label=='Creative plan' and validated_draft is not None:
                        mode_match = re.search(r'^Planned page (\d+).*Each page needs render_mode',str(exc))
                        constraints_match = re.search(r'^Planned page (\d+).*Exact mechanic (?:constraints|alias)',str(exc))
                        match = mode_match or constraints_match
                        plan_mode_base,plan_mode_number = (validated_draft,int(match[1])) if match else (None,None)
                        plan_repair_field = 'render_mode' if mode_match else 'mechanic_constraints'
                    if 'ONE shared source' in prompt and validated_draft is not None:
                        missing_exercise = (('Return exercise as the shared source' in str(exc)
                                             or 'Exercise recovery must return' in str(exc))
                                            and isinstance(validated_draft,dict)
                                            and not isinstance(validated_draft.get('exercise'),dict)
                                            and isinstance(validated_draft.get('html'),str))
                        if missing_exercise:
                            exercise_repair_base = validated_draft
                        elif exercise_repair_base is not None and isinstance(validated_draft.get('exercise'),dict):
                            exercise_repair_base = None
                        missing_manifest = (('Illustration manifest images must be a JSON list' in str(exc)
                                             or 'Supply 1-4 meaningful illustrations' in str(exc)
                                             or 'Render every purposeful exercise illustration' in str(exc))
                                            and isinstance(validated_draft,dict)
                                            and validated_draft.get('images') in (None,[])
                                            and isinstance(validated_draft.get('exercise'),dict)
                                            and isinstance(validated_draft.get('html'),str))
                        manifest_repair_base = validated_draft if missing_manifest else None
                        prompt_repair_base, prompt_repair_id = (validated_draft,prompt_match[1]) if prompt_match else (None,None)
                        if answer_match or math_match:
                            answer_repair_base, answer_repair_id = validated_draft, (answer_match or math_match)[1]
                            repair_calculation = math_match is not None and 'answer key must contain' not in str(exc)
                        else:
                            answer_repair_base, answer_repair_id = None, None
                        exact_repair_base = validated_draft if exact_wording_requires_content_repair(validated_draft,str(exc)) else None
                        if answer_match or math_match or prompt_match or exact_repair_base is not None:
                            layout_repair_base = None
                        elif (isinstance(validated_draft,dict) and isinstance(validated_draft.get('html'),str)
                              and isinstance(validated_draft.get('exercise'),dict)
                              and isinstance(validated_draft.get('images'),(list,dict))
                              and (layout_repair_base is not None or str(exc).startswith(
                                  ('Design overflow:', 'Design content extends outside printable bounds:', 'Visuals are too small',
                                   'Put ALL printed wording', 'Unknown or repeated exercise content slot',
                                   'Use every required exercise content slot')))):
                            layout_repair_base = validated_draft
                        content = json.dumps(validated_draft)
                    # Keep only the latest draft/correction instead of an expanding conversation.
                    messages = [messages[0], {'role':'user','content':prompt}]
                    if content:
                        messages.append({'role': 'assistant', 'content': content[:36000]})
                    repair = f'Correct only this unit and return complete JSON. Validation: {exc}'
                    if isinstance(exc, json.JSONDecodeError):
                        repair += (
                            ' Repair JSON serialization only: check missing commas, unescaped double quotes '
                            'inside the html string, and literal line breaks. Use single-quoted HTML attributes. '
                            'Preserve the exercise and design rather than inventing a different page.'
                            ' Return exactly ONE JSON object: no second object, explanations, or text '
                            'after the closing brace. Include every required field in that one object.'
                        )
                    asset_error = str(exc).lower()
                    if exercise_repair_base is not None:
                        repair += (
                            ' Return ONLY {"exercise":{...}}. exercise MUST be a JSON OBJECT, '
                            'not HTML, null, a string, an array or an omitted field. Use the ORIGINAL '
                            'page brief render_mode and mechanic and retain its actual student action. '
                            'For authored: {"exercise":{"render_mode":"authored",'
                            '"mechanic":"<planned mechanic>","goal":"<learning goal>",'
                            '"directions":"<concise task>","questions":[{"id":"1",'
                            '"prompt":"<student action>","answer":"<correct solution or success criterion>",'
                            '"space_mm":50}]}}. Add passage/captions or numeric calculation only if '
                            'needed for this original activity. For exact: {"exercise":{'
                            '"render_mode":"exact","mechanic":"<planned exact tool>",'
                            '"goal":"<learning goal>","visual":{"id":"<existing data-visual id>",'
                            '"question":1,"kind":"<planned exact tool>","<required puzzle fields>":"<values>"},'
                            '"questions":[]}}; supply real puzzle data from the exact tool contract, '
                            'not placeholder text. No parallel answers/calculations/visuals fields. '
                            'Python retains the original HTML and images, applies only exercise and '
                            'then checks task correctness, bindings and printable layout. '
                        )
                    if prompt_repair_base is not None:
                        repair += (
                            f' Correct ONLY exercise.questions id {prompt_repair_id} prompt to nonempty text '
                            'of at most 220 characters. Preserve every number, unit, condition, requested '
                            'student action and rounding instruction. Do not truncate mid-sentence or remove '
                            'a subtask. Keep answers, calculations, IDs, response spaces, images and HTML '
                            'unchanged. Return exercise.questions with the identified id and prompt; Python '
                            'applies only this prompt correction and validates the retained complete page. '
                        )
                    if answer_repair_base is not None:
                        repair += (
                            f' Correct ONLY the {"calculation and answer fields" if repair_calculation else "answer field"} for exercise.questions id {answer_repair_id}. '
                            'Return a nonempty concise solution or success criterion of at most 180 characters; '
                            'preserve every required value and essential condition. Do not truncate mid-sentence. '
                            'Keep the original question IDs, prompts, other calculations, response spaces, goal, '
                            'captions, HTML and illustration manifest unchanged. Python applies only this '
                            'identified field correction to the retained original page, then validates it normally. '
                        )
                    if exact_wording_requires_content_repair(validated_draft,str(exc)):
                        repair += (
                            ' This is an EXACT-PUZZLE CONTENT/BINDING repair, not a layout-only repair. '
                            'The graphic owns its verified instructions. Do not convert task directions into '
                            'exercise.captions or create caption_directions. Remove only parallel instructions '
                            'that duplicate the computed task; preserve genuinely additional student actions '
                            'as canonical questions with unused IDs, correct criteria and response space. '
                            'Do not rename generic shapes as cultural artifacts or claim unsupported art features. '
                            'Preserve the planned mechanic, visual data and already valid questions. Bind factual '
                            'context labels as captions, and match every remaining slot to an actual canonical '
                            'field. Exact pages have NO directions/passage slots. Return complete html, images '
                            'and exercise; Python validates this repaired shared content and the printable page. '
                        )
                    if layout_repair_base is not None:
                        repair += (
                            ' This is a layout-only correction: preserve the original exercise and images '
                            'manifest, including prompts, IDs, answers and response spaces. Python applies '
                            'ONLY the corrected HTML to that retained page, then validates all content, '
                            'except new exercise.captions may bind complete contextual labels already '
                            'printed in the retained HTML. Supply their exact original wording and one '
                            'matching caption_ID slot. Existing captions and all tasks remain unchanged. '
                            'Name/date are optional metadata, not exercise captions: keep at most one '
                            'name slot and one date slot. Do not invent new directions or turn a '
                            'count-and-write task into count-and-match. For exact pages the graphic '
                            'already prints its verified directions; do not add parallel puzzle wording. '
                            'print bounds and visual minimums again. Keep all existing data-content slots '
                            'and data-asset/data-visual IDs. '
                        )
                    if 'visuals are too small' in asset_error:
                        repair += (
                            ' Repair visual dimensions and layout ONLY, preserving exercise content and every '
                            'answer criterion, response space and image ID/prompt. Enlarge the useful artwork '
                            'rather than adding blank panels, logos or duplicate decorative thumbnails. '
                            'A main image around width:150mm;height:90mm provides 13500mm2; use dimensions '
                            'meeting the reported total and main-visual minimums. Count all margins, borders '
                            'and response spaces inside a 235mm height budget. Recompose panels and reduce '
                            'decorative spacing if needed; never shrink student text or essential work space. '
                            'Return the complete html, images and exercise. '
                            'For a page of tiny picture cards, recompose one large main picture and the '
                            'remaining supporting pictures instead of returning the same thumbnail grid. '
                            'Use the real manifest IDs exactly once. Example: a 145mm by 70mm main image '
                            'alone covers 10150 square mm; keep other pictures and work space in the '
                            'remaining height. New contextual labels must be canonical captions. '
                        )
                    if label == 'Creative plan' and ('mechanic' in asset_error or 'render_mode' in asset_error):
                        repair += (
                            ' Correct only the affected page briefs. render_mode exact uses a precise drawing '
                            'tool: maze, count, sort, pattern, matching, differences or balance (size comparison). '
                            'Use render_mode authored for drawing, coloring, crafts, role-play, original writing '
                            'and other creative tasks; preserve their original concepts and layouts. Do not replace '
                            'a creative activity with a generic sorting puzzle to satisfy the schema. Distinct '
                            'authored activities may share a mechanic label. For repeated exact tasks with the '
                            'same learning goal, vary the concrete task of the identified page only. Keep all '
                            'other page briefs and the pack art direction. Return the complete plan.'
                        )
                    if ('printed wording' in asset_error or 'content slot' in asset_error or
                            'required exercise content' in asset_error or 'inferred content slot' in asset_error or
                            'entire text container' in asset_error or 'use a text container' in asset_error):
                        repair += (
                            ' Repair content binding only, not the activity. Return html, images, exercise. '
                            'All task wording belongs in exercise.directions, passage or questions[].prompt; '
                            'For a contextual heading or illustration label, preserve its wording in '
                            'exercise.captions [{id:"context",text:"original label"}] and replace the raw '
                            'HTML text with an empty data-content="caption_context" slot. Use child-friendly '
                            'vocabulary for younger grades; do not move instructions or solutions into captions. '
                            'Retain existing correct wording and answer/criterion. Layout containers '
                            'use data-content="title", "directions", "passage", "name", "date", "caption_ID" or "question_ID". '
                            'Bind the WHOLE container with one data-content attribute rather than only its '
                            'first text chunk. Move any genuinely additional wording into a separate canonical '
                            'question/direction/caption slot; never discard it as formatting. '
                            'Use each required slot once, with no duplicate unbound instructions or labels. '
                            'Keep image elements outside text slots and retain every graphic ID and task. '
                            'Use div or section for layout wrappers, not unsupported semantic tags. '
                            'Do not delete a task to make the markup validate.'
                        )
                    if 'exact planned activity title' in asset_error:
                        repair += (
                            ' Repair only the visible activity heading to match the supplied title words. '
                            'Page/activity numbering is separate metadata and need not be part of the title. '
                            'Retain every task, illustration manifest, visual, answer and calculation. '
                            'Do not redesign the exercise to correct its heading.'
                        )
                    if 'symbol' in asset_error or 'supported shape' in asset_error:
                        repair += (
                            f' Repair only the identified exact visual item. Supported shapes: {sorted(SHAPES)}. '
                            f'Supported colors: {sorted(COLORS)}. Every items object needs shape, color and '
                            'size (small or large). Difference changes.value must be valid for its field. '
                            'Keep the grouping/difference logic and all numbered tasks coherent; update '
                            'directions if a subject must change. Use images for other original illustrated '
                            'subjects, but never replace an exact-answer puzzle with AI art. Return the '
                            'complete page and preserve images, visuals, answers and calculations.'
                        )
                    if ('exercise question ids' in asset_error or 'parallel directions' in asset_error
                            or 'verified directions' in asset_error or 'unbound wording' in asset_error) and 'ONE shared source' in prompt:
                        repair += (
                            ' Resolve content and numbering together in the CURRENT shared exercise schema. '
                            'If render_mode is exact, exercise.visual owns its printed question number and '
                            'computed answer; do not also list that puzzle in exercise.questions. '
                            'Omit exercise.directions and exercise.passage AND their HTML slots for exact pages. '
                            'Remove only duplicate raw puzzle directions/answers from HTML; the exact graphic '
                            'already supplies its verified action. Keep all genuinely additional student actions '
                            'in exercise.questions with unused IDs, correct criteria and matching question_ID slots. '
                            'Keep context in title or short non-instruction exercise.captions, not invented '
                            'instructions such as connecting pictures on a count-and-write graphic. '
                            'For authored pages retain canonical directions and every task; fix invalid/duplicate '
                            'IDs and update each corresponding question_ID slot without changing the task. '
                            'Return ONLY html, images and exercise. Preserve the planned mechanic and graphic '
                            'data; never replace the precise puzzle with an AI illustration.'
                        )
                    if ('visual question' in asset_error or 'visual needs' in asset_error or
                            'visual ids' in asset_error or 'data-visual' in asset_error or
                            'visuals must' in asset_error):
                        if 'ONE shared source' in prompt:
                            repair += (
                                ' Repair exercise.visual (singular), never a top-level visuals list. '
                                'It needs id matching [a-z][a-z0-9_]{0,30}, question as a JSON integer 1-30 '
                                'and kind with the required puzzle data. Its question number is reserved for '
                                'the computed puzzle, not a duplicate exercise.questions item. '
                                'Use exactly the same id in img data-visual. Keep artwork and all actual tasks. '
                                'Return ONLY html, images and exercise; no independent answers or calculations. '
                            )
                        else:
                            repair += (
                                ' Repair exact visual metadata and references together. Each visuals object '
                                'needs id matching [a-z][a-z0-9_]{0,30}, a unique question JSON integer 1-30 '
                                'matching its printed task, and kind with all required puzzle fields. '
                                'Use the exact SAME id in img data-visual. Do not use zero, null, string '
                                'question numbers, illustration prompts or page labels as metadata. '
                                'Preserve puzzle content, artwork and calculations. Return the complete page '
                                'including html, images, visuals and answers; do not replace a puzzle with '
                                'an AI illustration or invent missing task numbers.'
                            )
                    if ('calculation' in asset_error or 'arithmetic' in asset_error or 'only numbers' in asset_error
                            or 'only integer/decimal literals' in asset_error):
                        if 'ONE shared source' in prompt:
                            repair += (
                                ' Correct ONLY exercise.questions[].calculation and its answer field. '
                                'expression must compute the numeric result, e.g. "20-8" for x+8=20, '
                                '"200*15/100" for 15 percent of 200, or "12.50+7.25" for a cost sum. '
                                'No variable names, equals signs, functions, units, verbal formulas or powers. '
                                'calculation.answer is the final number or fraction string, not an expression. '
                                'For a question with no arithmetic, omit calculation from that question; '
                                'never add a top-level calculations field. Keep printed question text, IDs, '
                                'response spaces, image manifest and planned mechanic. Return html with EMPTY '
                                'data-content slots, images, and the complete exercise specification.'
                            )
                        else:
                            repair += (
                                ' Repair calculations only. Every calculations item must have exactly '
                                'question (unique nonempty string of 1-20 characters matching the printed task, '
                                'e.g. "1" or "2A"), expression (numeric computation), and answer (final value). '
                                'Do not omit question, use null, or substitute question_number/id/number fields. '
                                'If the worksheet has no arithmetic, return calculations: []. '
                                'Expression must be a numeric computation such as '
                                '"12.50+7.25", "3/4+1/8" or "20*15/100", not an equation or word problem. '
                                'No unknowns, equals signs, currency symbols, units, powers or percent signs '
                                'inside expression. For a missing-number task, express the numeric operation '
                                'that computes the missing value (e.g. "20-8", not "x+8=20"). Put units and '
                                'question wording in html and the final value in answer. Preserve the artwork '
                                'and question/answer references; do not replace the exercise to fix notation.'
                            )
                    if ('illustration' in asset_error or 'data-asset' in asset_error or
                            'asset mismatch' in asset_error):
                        repair += (
                            ' Repair the image manifest and HTML together. Return images as a JSON list of 1-4 '
                            'objects, each exactly {"id":"short_lowercase_id","prompt":"complete visual prompt"}. '
                            'images=[] is allowed ONLY on a student page containing valid exact visuals. '
                            'Every img uses EITHER data-asset for one images[].id OR data-visual for one '
                            'visuals[].id; never both. Declare and use every ID. Do not use src attributes. '
                            'Keep exact visual specifications and their question numbers intact. Never return '
                            'a null/string/object instead of an images list or delete task artwork. '
                            'Do not rename an ID on only one side: synchronize images[].id and every data-asset '
                            'reference in the same response. Keep the existing activity content and layout.'
                        )
                        if 'ONE shared source' in prompt:
                            repair += (
                                ' Repair the reported illustration ID lists without redesigning the exercise. '
                                'For missing HTML IDs, place each existing declared image in its intended panel. '
                                'For undeclared HTML IDs, restore the correct declared reference; if the panel '
                                'requires a genuinely different subject, supply its own complete prompt and ID '
                                'within the four-image limit, never reuse an unrelated picture. '
                                'For repeated IDs, remove only accidental duplicate decorative placements; '
                                'retain every task-relevant panel with distinct meaningful images if needed. '
                                'Preserve exercise fields, questions, answers, response space and planned intent. '
                                'Use exercise.visual (singular) for exact graphics, not a top-level visuals list. '
                                'Return ONLY html, images and exercise with empty data-content slots. '
                            )
                        if label == 'Cover design':
                            repair += (
                                ' This is a COVER: keep at least one purposeful illustration and place it visibly '
                                'in the cover HTML with <img data-asset=...>. Do not solve the mismatch by deleting '
                                'the image element or returning an unused images entry.'
                            )
                    if asset_error.startswith('design overflow:') or 'printable bounds' in asset_error:
                        repair += (
                            ' Recompose this same activity more compactly. Budget at most 235mm of content '
                            'height including headings, margins, borders and response spaces. Keep total '
                            'table widths including cell padding and spacing below 186mm. Avoid explicit '
                            'percentage widths on table cells; use equal auto-width cells or a stacked layout. '
                            f'Do not hide overflow, remove questions, shrink text below {minimum_font}pt or remove essential '
                            'response space. '
                            + ('Return the complete page with html, images and exercise; no parallel answer/visual/calculation drafts. '
                               if 'ONE shared source' in prompt else
                               'Return the complete page including images, visuals, answers and calculations. ')
                            + 'Preserve image IDs/prompts and data-asset/data-visual '
                            'references together; never omit the images list during a layout repair.'
                        )
                        if 'ONE shared source' in prompt:
                            repair += (
                                ' Preserve exercise fields, every question, answer criterion and space_mm. '
                                'Remove oversized fixed heights/min-heights from outer panels (use auto height), '
                                'stack or regroup existing content, and reduce decorative padding/margins. '
                                'Keep exact graphic labels readable and purposeful art large enough for the grade. '
                                'Count each question space_mm PLUS its prompt, 3mm top margin and border in the '
                                'vertical budget. A full-page height wrapper beneath a heading cannot fit. '
                                'Do not expand wording during repair or introduce independent layout text. '
                            )
                        if label == 'Cover design':
                            repair += (
                                ' The cover also reserves 41mm for the real store logo: keep YOUR fragment '
                                'below 215mm, ideally 205mm.'
                            )
                    repair += (f' All student text, including captions, must be at least {minimum_font}pt. '
                               'Python raises smaller inline sizes to this floor BEFORE checking fit. '
                               'Budget the layout at this readable size; use shorter directions and fewer '
                               'decorative headings without removing tasks or shrinking response areas.')
                    if 'ONE shared source' in prompt:
                        repair += (' This is a bound exercise page. Return ONLY html, images, exercise. '
                                   'Put corrections in exercise.visual or exercise.questions and use EMPTY '
                                   'data-content slots in html. Do not return legacy visuals/answers/calculations '
                                   'fields or fill slots with text. Preserve planned render_mode and mechanic.')
                    if plan_mode_base is not None:
                        brief = plan_mode_base['pages'][plan_mode_number-1]
                        if plan_repair_field=='mechanic_constraints':
                            from core.response_schemas import mechanic_constraints_schema
                            messages = [messages[0],{'role':'user','content':
                                'Repair ONLY mechanic_constraints for the retained planned page. Keep its '
                                'mechanic, render_mode, title, concept, goal and layout unchanged. Matching allows '
                                'only mode shadow/identical; sort allows only attribute shape/color/size. '
                                'All other tools require an empty object {}. Honor explicit rules in the original '
                                'concept and aliases; do not change the student task. Return ONLY '
                                '{"pages":[{"page_number":'+str(plan_mode_number)+',"mechanic_constraints":{...}}]}. '
                                'Allowed options: '+json.dumps(mechanic_constraints_schema(brief['mechanic']))+
                                '\nRetained brief: '+json.dumps(brief)+'\nValidation: '+str(exc)}]
                        else:
                            messages = [messages[0],{'role':'user','content':
                            'Repair ONLY the render_mode of this existing activity brief. Do not regenerate '
                            'the plan, mechanic, title, learning goal, concept or layout. Select the literal '
                            'string "exact" for a supported precise puzzle, or "authored" for an original '
                            'open task. Return one JSON object: {"pages":[{"page_number":'+str(plan_mode_number)+
                            ',"render_mode":"authored"}]}. Use the appropriate single mode, not "exact or '
                            'authored". Existing brief:\n'+json.dumps(brief)+'\nValidation: '+str(exc)}]
                    elif prompt_repair_base is not None:
                        from core.response_schemas import prompt_repair_messages
                        messages = prompt_repair_messages(messages[0],prompt_repair_base,prompt_repair_id,str(exc))
                    elif isinstance(exc,json.JSONDecodeError):
                        messages = [messages[0],{'role':'user','content':
                            'Repair JSON serialization only for the response below. Return exactly ONE '
                            'JSON object, with every original field and value preserved. No prose, fences, '
                            'duplicate objects or fields after the closing brace. Escape embedded double '
                            'quotes and line breaks. Do not redesign the activity or invent new exercises. '
                            'If an explanation follows the object, remove only that explanation; preserve '
                            'all exercise and illustration data inside the object. Parser error: '+str(exc)+
                            '\nResponse to serialize:\n'+(content or '')[:36000]}]
                    elif layout_repair_base is not None:
                        messages = [messages[0],{'role':'user','content':
                            'Repair ONLY this existing printable layout. Return JSON containing html only; '
                            'Repair visual dimensions and layout ONLY, preserving the original task. '
                            'do not repeat images, questions, answers or the complete exercise. Preserve '
                            'every data-content slot and data-asset/data-visual ID exactly once. Keep all '
                            'task wording and response space unchanged; no new headings or captions. '
                            'Python applies ONLY the corrected HTML, plus captions binding exact original labels. '
                            f'A4 content width 186mm, height 265mm; minimum text {minimum_font}pt. '
                            f'Useful visual area must total at least {layout_visual_area} square mm, '
                            f'with one main visual at least {layout_visual_area*.55:g} square mm. '
                            'Recompose large artwork and work panels; no fixed full-page-height wrapper. '
                            'Reduce decorative spacing; never shrink student text or response space. '
                            'Example main-image style: width:150mm;height:90mm; keep artwork uncropped. '
                            'If an existing raw context label needs binding, you may additionally return '
                            'exercise.captions with its EXACT already printed wording and matching slot. '
                            'Example: captions [{id:"context",text:"original label"}] and an empty '
                            'data-content="caption_context" text container. '
                            'Never add new wording or alter an existing caption. Validation: '+str(exc)+
                            '\nOriginal grade/context guidance:\n'+prompt[:3500]+
                            '\nRetained page:\n'+json.dumps(layout_repair_base)}]
                    elif manifest_repair_base is not None:
                        refs = illustration_references(manifest_repair_base['html'])
                        instructions = (
                            'Recover ONLY missing illustration prompts for this existing classroom activity. '
                            'Return JSON with images as a NONEMPTY list of 1-4 objects {id,prompt}; never null. '
                            'Each prompt must be <=650 characters, original and meaningful for the supplied task, '
                            'grade and art direction. No text, numbers, worksheets or borders in generated art. '
                            'Keep the exercise, answers, questions and response space unchanged. '
                        )
                        if refs:
                            instructions += ('Use these exact existing image slot IDs: '+json.dumps(refs)+
                                             '. Return ONLY images; the original HTML will be retained. ')
                        else:
                            instructions += (
                                'Also return html with the same canonical content slots and added visible '
                                'data-asset images. Preserve all original task wording, panels and work space; '
                                'choose useful print dimensions meeting the original grade guidance. '
                            )
                        messages = [messages[0],{'role':'user','content': instructions+
                                    '\nGrade/context/art guidance:\n'+prompt[:7000]+
                                    '\nExisting page (data to preserve):\n'+json.dumps(manifest_repair_base)}]
                    else:
                        messages.append({'role': 'user', 'content': repair})
                    time.sleep(min(2 ** max(validation_attempt - 1, 0) + random.random(), 10))
                except Exception as exc:
                    failure = safe_api_error(provider, exc, model=model)
                    errors.append(f'{label}: {failure}')
                    LOGGER.warning('%s', errors[-1])
                    if not failure.retryable:
                        break

                    # Transport/provider failures do not consume a content-validation attempt.
                    transport_failures += 1
                    if transport_failures >= max_transport_failures:
                        break
                    base_delay = min(60.0, 5.0 * (2 ** (transport_failures - 1)))
                    delay = max(base_delay, failure.retry_after or 0) + random.random()
                    LOGGER.info(
                        '%s: transient Gemini failure; keeping the same key and retrying in %.1fs (%s/%s)',
                        label, delay, transport_failures + 1, max_transport_failures)
                    time.sleep(delay)
        finally:
            api.close()
    raise ActivityGenerationError('; '.join(dict.fromkeys(errors))) from None

def validate_plan(raw: dict, count: int, *, require_coherent: bool = False) -> dict:
    """Validate bounded art direction and distinct activity concepts without a type menu."""
    if not isinstance(raw, dict):
        raise ValueError('Plan must be an object')
    plan = deepcopy(raw)
    for key, limit in {'title': 80, 'overview': 350, 'art_direction': 650,
                       'character_description': 350, 'cover_brief': 800}.items():
        plan[key] = _text(plan.get(key), key, limit)
    if not isinstance(plan.get('pages'), list) or len(plan['pages']) != count:
        raise ValueError(f'Plan exactly {count} student activities')
    for number,page in enumerate(plan['pages'],1):
        if not isinstance(page, dict):
            raise ValueError('Each planned page must be an object')
        for key in ('title', 'learning_goal', 'activity_concept', 'layout_brief'):
            page[key] = _text(page.get(key), key, 80 if key == 'title' else 650)
        page['title'] = _text(activity_title(page['title']), 'activity title without page label', 80)
        if require_coherent:
            try:
                validate_brief(page,planning=True)
            except ValueError as exc:
                raise ValueError(f'Planned page {number} ({page["title"]!r}): {exc}') from None
    for key in ('title', 'activity_concept', 'layout_brief'):
        if len({p[key].strip().casefold() for p in plan['pages']}) != count:
            raise ValueError(f'Each page needs a different {key}; do not repeat a worksheet pattern')
    if require_coherent:
        groups = {}
        for number,page in enumerate(plan['pages'],1):
            if page['render_mode']=='exact':
                key = (page['mechanic'],' '.join(page['learning_goal'].split()).casefold(),
                       tuple(sorted(page.get('mechanic_constraints',{}).items())))
                groups.setdefault(key,[]).append(number)
        repeated = [numbers for numbers in groups.values() if len(numbers)>2]
        if repeated:
            raise ValueError(f'Repeat the same exercise mechanic and learning goal at most twice for exact puzzles; '
                             f'vary the actual task on pages {repeated}. Authored drawing/craft pages may share a '
                             'mechanic when their concrete concepts and compositions differ')
    return plan


def _normalize_asset_prompt(value, asset_id: str, *, cover: bool = False) -> str:
    """Recover harmless missing/oversized model prompts without another provider retry."""
    if isinstance(value, str):
        prompt = ' '.join(value.split())
    else:
        prompt = ''
    if prompt:
        return prompt[:650]
    role = 'cover' if cover else 'classroom activity'
    return (
        f"Original purposeful educational illustration for this {role}, asset {asset_id}. "
        "Use the page context and art direction to depict one clear age-appropriate visual subject. "
        "No text, letters, numbers, logos, labels, borders, answer marks or worksheet layout."
    )[:650]


def _consolidate_image_manifest(design: dict, *, cover: bool = False) -> tuple[list[dict], str]:
    """Limit a model-authored page to four usable assets without another LLM retry."""
    html = design['html']
    refs = list(dict.fromkeys(
        re.findall(r"<img\b[^>]*\bdata-asset=['\"]([^'\"]+)['\"]", html, re.I)
    ))
    raw_images = design.get('images')
    valid = []
    if isinstance(raw_images, list):
        for asset in raw_images:
            if not isinstance(asset, dict):
                continue
            asset_id = str(asset.get('id', ''))
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', asset_id):
                continue
            if any(existing['id'] == asset_id for existing in valid):
                continue
            valid.append({
                'id': asset_id,
                'prompt': _normalize_asset_prompt(asset.get('prompt'), asset_id, cover=cover)
            })

    # Prefer assets actually referenced by the HTML, then any remaining valid
    # manifest entries. If Gemini omitted the manifest, synthesize from HTML IDs.
    by_id = {asset['id']: asset for asset in valid}
    unknown = [asset_id for asset_id in refs if asset_id not in by_id]
    missing = [asset_id for asset_id in by_id if asset_id not in refs]
    if unknown and len(unknown) == len(missing):
        # Rebind misspelled slots before inventing fallback prompts or extra art.
        html = _synchronize_asset_references(html, list(by_id))
        refs = list(dict.fromkeys(re.findall(
            r"<img\b[^>]*\bdata-asset=['\"]([^'\"]+)['\"]", html, re.I)))
    ordered = []
    for asset_id in refs:
        if asset_id in by_id:
            ordered.append(by_id[asset_id])
        else:
            ordered.append({
                'id': asset_id,
                'prompt': _normalize_asset_prompt('', asset_id, cover=cover)
            })
    for asset in valid:
        if asset['id'] not in {item['id'] for item in ordered}:
            ordered.append(asset)

    if not ordered:
        fallback_id = 'cover_art' if cover else 'scene'
        ordered = [{
            'id': fallback_id,
            'prompt': _normalize_asset_prompt('', fallback_id, cover=cover)
        }]

    retained = ordered[:4]
    retained_ids = [asset['id'] for asset in retained]

    # Remap excess HTML slots onto retained assets in stable round-robin order.
    excess = [asset_id for asset_id in refs if asset_id not in set(retained_ids)]
    if excess:
        for index, old in enumerate(excess):
            new = retained_ids[index % len(retained_ids)]
            html = re.sub(
                rf"(\bdata-asset=['\"]){re.escape(old)}(['\"])",
                rf"\g<1>{new}\g<2>", html, flags=re.I)

    return retained, html


def _synchronize_asset_references(html: str, ids: list[str]) -> str:
    """Repair simple model mistakes between images[].id and HTML data-asset references."""
    refs = re.findall(r"<img\b[^>]*\bdata-asset=['\"]([^'\"]+)['\"]", html, re.I)
    declared = list(ids)
    declared_set, referenced_set = set(declared), set(refs)

    unknown = list(dict.fromkeys(ref for ref in refs if ref not in declared_set))
    missing = [asset_id for asset_id in declared if asset_id not in referenced_set]

    # If the model used the right number of image slots but invented different IDs,
    # bind those slots to the declared assets instead of spending another LLM retry.
    if unknown and len(unknown) == len(missing):
        mapping = dict(zip(unknown, missing))
        for old, new in mapping.items():
            html = re.sub(
                rf"(\bdata-asset=['\"]){re.escape(old)}(['\"])",
                rf"\g<1>{new}\g<2>", html, flags=re.I)
        refs = re.findall(r"<img\b[^>]*\bdata-asset=['\"]([^'\"]+)['\"]", html, re.I)
        referenced_set = set(refs)
        missing = [asset_id for asset_id in declared if asset_id not in referenced_set]

    # The most common failure is a valid image manifest with no matching <img>.
    # Add only the missing declared assets, using conservative printable dimensions.
    if missing:
        injected = ''.join(
            f"<img data-asset='{asset_id}' style='width:80mm;height:55mm'/>"
            for asset_id in missing
        )
        html = html + injected

    return html


def validate_design(raw: dict, font: int, *, cover: bool = False,
                    quality: dict | None = None, expected_title: str | None = None,
                    require_coherent: bool = False, brief: dict | None = None) -> dict:
    """Require complete art-backed HTML and preflight it at actual print dimensions."""
    if not isinstance(raw, dict):
        raise ValueError('Design must be an object')
    design = deepcopy(raw)
    design['html'] = _text(design.get('html'), 'html', 18000)
    if quality is not None:
        design['html'] = reveal_print_content(design['html'])
    if require_coherent and not cover:
        compile_exercise(design, quality or {}, expected_title or '', brief)
    if cover:
        # Cover art has no exercise numbers. Ignore unused exercise metadata,
        # but never silently remove a visible puzzle from authored markup.
        if re.search(r'<img\b[^>]*\bdata-visual\s*=', design['html'], re.I):
            raise ValueError('Cover illustrations must use data-asset and images; '
                             'move numbered puzzles to student pages and return visuals=[]')
        design['visuals'] = []
        design.pop('answers', None)
        design.pop('calculations', None)
    else:
        answers = design.get('answers')
        if isinstance(answers, list) and 1 <= len(answers) <= 30 and all(isinstance(a, str) and a.strip() for a in answers):
            answers = '; '.join(answers)
        if answers == '' and design.get('visuals'):
            design['answers'] = ''  # All questions may be inside exact visuals.
        else:
            design['answers'] = _text(answers, 'answers', 4000)
    if not cover:
        normalize_visual_metadata(design)
    page_visuals(design)
    if quality is not None:
        # Never silently replace, merge or invent artwork in newly generated books.
        images = design.get('images')
        if not isinstance(images, list) or len(images) > 4 or (not images and (cover or not design.get('visuals'))):
            detail = ('missing' if 'images' not in design else
                      f'list with {len(images)} entries' if isinstance(images, list) else type(images).__name__)
            raise ValueError('Supply 1-4 meaningful illustrations, or exact visuals with images=[]; '
                             f'images is {detail}. Return a JSON list; an empty list needs exact visuals.')
        ids = set()
        for asset in images:
            if not isinstance(asset, dict) or not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', str(asset.get('id',''))):
                raise ValueError('Illustration IDs must be short lowercase identifiers')
            if asset['id'] in ids:
                raise ValueError('Illustration IDs must be unique; do not merge distinct subjects')
            ids.add(asset['id'])
            asset['prompt'] = _text(asset.get('prompt'), 'illustration prompt', 650)
        refs = set(re.findall(r'<img\b[^>]*\bdata-asset=[\'\"]([^\'\"]+)[\'\"]', design['html'], re.I))
        if refs != ids:
            raise ValueError('Match every image id to exactly its intended data-asset reference; do not substitute pictures')
        design['quality_profile'] = {
            'visual_area_mm2': quality.get('visual_area_mm2', 6500),
            'minimum_text_pt': quality.get('minimum_text_pt', 11)}
    else:
        images, design['html'] = _consolidate_image_manifest(design, cover=cover)
    design['images'] = images
    ids = {asset['id'] for asset in images}
    ordered_ids = [asset['id'] for asset in images]

    design['html'] = _synchronize_asset_references(design['html'], ordered_ids)
    html_refs = set(re.findall(r"<img\b[^>]*\bdata-asset=['\"]([^'\"]+)['\"]", design['html'], re.I))
    if html_refs != ids:
        declared = ', '.join(sorted(ids)) or 'none'
        referenced = ', '.join(sorted(html_refs)) or 'none'
        raise ValueError(f'Image asset mismatch after deterministic repair: declared IDs [{declared}]; HTML data-asset IDs [{referenced}]')
    if quality is not None and not cover:
        validate_exercises(design, quality, expected_title)
    check_page(design, font, cover=cover)
    return design


def compact_answers(page: dict, number: int) -> dict:
    """Shorten only an oversized key; never redesign the already validated worksheet."""
    if page.get('exercise_binding') or len(page['answers']) <= 300:
        return page
    def validate_key(raw):
        """Require a concise, nonempty key without accepting arbitrary response fields."""
        if not isinstance(raw, dict):
            raise ValueError('Return an object containing answers')
        return {'answers': _text(raw.get('answers'), 'condensed answers', 300)}
    result = ask_json('Condense this classroom answer key to at most 300 characters. '
                      'Preserve EVERY numbered answer, correct value and essential condition; '
                      'remove repeated questions, explanations and teaching tips. Do not alter '
                      'the worksheet. Return JSON {"answers":"..."}.\n'
                      + json.dumps({'worksheet': page['html'], 'answers': page['answers']}),
                      validate_key, f'Answer key {number}', tokens=1200)
    return dict(page, answers=result['answers'])


def compact_shared_answers(pack: dict, config: dict) -> None:
    """Shorten canonical answer fields only when the measured final key cannot fit."""
    payload = [{'page_number':n,'questions':page['exercise'].get('questions',[])}
               for n,page in enumerate(pack['pages'],1)]
    def validate(raw):
        """Require every page and question ID, then revalidate the unchanged student tasks."""
        rows = raw.get('pages') if isinstance(raw,dict) else None
        if not isinstance(rows,list) or len(rows)!=len(payload):
            raise ValueError('Return every page exactly once for shared answer compaction')
        by_number = {}
        for row in rows:
            if not isinstance(row,dict) or type(row.get('page_number')) is not int:
                raise ValueError('Answer compaction page_number must be an integer')
            n = row['page_number']
            if n not in range(1,len(payload)+1) or n in by_number:
                raise ValueError('Unexpected or duplicate answer compaction page')
            previous = pack['pages'][n-1]
            expected = {q['id'] for q in previous['exercise'].get('questions',[])}
            answers = row.get('answers')
            if not isinstance(answers,list) or len(answers)!=len(expected):
                raise ValueError('Preserve every shared question answer; exact-only pages have answers=[]')
            replacements = {}
            for item in answers:
                if not isinstance(item,dict) or item.get('id') not in expected or item['id'] in replacements:
                    raise ValueError('Preserve exact question IDs in shared answer compaction')
                replacements[item['id']] = _text(item.get('answer'),'compact shared answer',90)
            exercise = deepcopy(previous['exercise'])
            originals = {q['id']:q['answer'] for q in exercise.get('questions',[])}
            for q in exercise.get('questions',[]): q['answer'] = replacements[q['id']]
            page = validate_design({'html':previous['source_layout'],'images':deepcopy(previous['images']),
                                    'exercise':exercise},config['student_font_pt'],quality=config,
                                   expected_title=previous['title'],require_coherent=True,
                                   brief=previous.get('planned_intent'))
            page.update(title=previous['title'],page_number=n,answer_key_original=originals)
            by_number[n] = page
        return {'pages':[by_number[n] for n in range(1,len(payload)+1)]}
    result = ask_json(
        'The final answer sheet is too long at measured A4 print size. Shorten ONLY the answer '
        'fields in these shared exercise questions to <=90 characters each. Preserve every correct '
        'solution, numeric value and essential success condition. Do not alter question IDs, prompts, '
        'calculations, tasks, visual components or layouts. Exact puzzle solutions are generated by '
        'Python and are not included here. Return JSON {"pages":[{"page_number":1,"answers":'
        '[{"id":"1","answer":"concise complete solution"}]}]}. Include every page, including '
        'answers=[] for pages with no questions. These fields will replace canonical exercise answers '
        'and receive text proofreading before use. Original shared questions:\n'+json.dumps(payload),
        validate,'Shared answer-sheet compaction',6000)
    pack['pages'] = result['pages']
    pack['answer_key_compacted'] = True


def layout_contract(font: int, minimum_text_pt: int = 11, *, cover: bool = False, coherent: bool = False) -> str:
    """Describe the print boundary without prescribing a reusable composition."""
    if cover:
        return f'''Return JSON containing html (one complete fragment, <=18000 chars), images
(1-4 objects with short lowercase id and original illustration prompt <=650 chars), visuals: [].
This is a decorative COVER, with the title, grade band and a short descriptive subtitle.
No exercise, question numbers, puzzle components, calculations, answers or student directions.
Use only images plus <img data-asset="id" style="width:175mm;height:125mm"/> for cover art.
Declare and use every image ID. Do not use data-visual. All images need explicit width and height
in mm and are fitted without cropping. Prompts describe original art without lettering or logos.
Canvas: A4 portrait, width 186mm. Python reserves 41mm above this fragment for the REAL store logo.
Keep YOUR composition at most 215mm high, ideally 205mm including all margins and padding.
Minimum student font: {minimum_text_pt}pt. Use {font}pt or larger for the subtitle and larger title.
Choose an original palette, composition, borders and hierarchy matching the pack art direction.
Allowed tags: {sorted(TAGS)}. Allowed CSS properties: {sorted(PROPERTIES)}.
Only inline styles; no html/head/body/style tags, external files, classes, SVG, scripts or URLs.
Use positive mm dimensions, valid colors, numeric line-height >=1.15 and font-size in pt.
No positioning, CSS grid, floats, transforms, hidden overflow or negative dimensions.
Do not invent certifications, reading-level labels or series numbers. Do not repeat the store logo.
'''
    if coherent:
        return EXERCISE_CONTRACT + BOUND_VISUAL_CONTRACT + f'''
Layout geometry: A4 portrait, 186mm content width; aim for <=235mm total height including all
borders, margins, response space and wrapping. No clipping or text shrinking to force a fit.
Minimum student font: {minimum_text_pt}pt; use {font}pt or larger for ordinary student wording.
Allowed tags: {sorted(TAGS)}. Allowed inline CSS: {sorted(PROPERTIES)}.
Only inline styles. No external resources, src attributes, classes, scripts, raw SVG, positioning,
grid, transforms, negative dimensions or hidden overflow. Use positive mm dimensions and pt fonts.
Images use data-asset and images:[{{id,prompt}}]; every prompt <=650 chars. 1-4 purposeful images,
or images=[] when exact visuals dominate. Every image/visual needs explicit width AND height in mm.
Keep a main visual at least 120x80mm; total visual area >=10000mm2 lower grades, 8000 middle, 6000 upper.
For younger grades, fill the workspace with big usable visual material, not tiny mascot headers.
Choose original composition, rich palette, panels and hierarchy suited to this activity. Ample
response space belongs in questions[].space_mm; do not add separate unbound response tasks.
No teacher guide or answers printed on student pages. Do not print independent activity numbers
in html: task numbers come from question IDs and exact visual.question. The title is a filled slot.
'''
    return VISUAL_CONTRACT + f'''Return JSON with html (one complete HTML fragment, <=18000 chars), images
(0-4 objects with id and prompt <=650 chars; at least one unless exact visuals fill the page), and answers (one concise string <=300 chars,
number EVERY answer to match the student tasks; include a sample/criterion for open responses).
Minimum student font: {minimum_text_pt}pt (mandatory for every caption and label).
Canvas: A4, 186mm wide, content at most 265mm high. No html/head/body/style tags.
Choose YOUR OWN layout, palette, typographic hierarchy, borders, panels and response spaces.
Allowed tags: {sorted(TAGS)}. Only inline style attributes; no classes or external files.
Allowed CSS properties: {sorted(PROPERTIES)}. Use valid simple CSS, positive mm dimensions,
percent widths, colors, numeric line-height >=1.15. Font-size in pt, {minimum_text_pt}-40pt; px
is converted at 0.75pt per px and smaller inline sizes are raised to {minimum_text_pt}pt before print checks. Student text
should usually be {font}pt or larger. Use tables or flex for columns; no CSS grid, positioning,
floats, transforms, overflow hiding, scripts, SVG, negative spacing, URLs or font imports.
Images: <img data-asset="asset_id" style="width:80mm;height:55mm"/>.
Declare and use every image. All images need BOTH explicit width and height, with height in mm.
Images are fitted without cropping. Illustration prompts must describe original meaningful
scenes or objects without text, labels, numbers, page borders or worksheet layouts.
Include calculations: [] or [{{"question":"2A","expression":"34+23","answer":57}}] for EVERY
arithmetic question, including missing-number problems (expression computes the missing value).
Each item requires question as a UNIQUE nonempty JSON string <=20 characters matching the printed
task label, e.g. "1" or "2A". Never omit question or rename it to question_number, number or id.
If no arithmetic appears, return calculations: []. Visuals question is an integer; calculations
question is a string label. Preserve these distinct schemas.
Expressions contain numeric integer/decimal literals, parentheses and + - * / only. Use "20-8"
for an unknown in x+8=20, "20*15/100" for a percentage; put equations, units and labels in html.
No variables, equals signs, currency symbols, powers or percent signs inside expression.
Python checks arithmetic. Match every printed question and answer exactly. Keep answers concise.
Python renders all written content. Draw exact quantities, diagrams, number lines, answer
boxes and symbols using HTML/text; never depend on image-model accuracy for a numeric answer.
Do not put solutions in student HTML. Include clear directions, numbered tasks, and sufficient
writing/cutting/drawing space appropriate to the activity. Never refer to missing materials.
Use normal document flow; aim for 235mm total content height, leaving 30mm safety for wrapping.
Plan a height budget: heading/name/directions <=40mm, main visual 90-140mm, response area
40-60mm, remaining borders/margins <=15mm. Choose values whose sum stays within 235mm.
For Pre-K-K: 1-2 short adult-read directions, at most 3 task items, no repeated instruction
paragraphs below picture cards. Keep large objects and usable hands-on response space.
Include padding, margins, borders and table spacing in the 186mm width budget.
Prefer auto-width table cells; percentage cell widths plus padding may overflow.
Use white-space:normal, pre-wrap or pre-line if needed. Long text and answer lines must wrap.
Python can reflow oversized table columns and reduce excessive paragraph/cell spacing,
but it will not shrink text, remove questions, or reduce explicit response-area heights.
Use ONE main activity on each page. Do not append the same reflection question to every activity.
For younger grades use picture cards, a large illustrated scene, hands-on visual challenges and generous
response space, not small mascot thumbnails above text boxes. At most FOUR card columns; keep labels
unbroken and readable. At least one main visual should be around 120x80mm or larger.
For grades Pre-K-K and 1st-2nd, use at least 10000 square mm total meaningful visual area; 3rd-4th
at least 8000; 5th-6th at least 6000. Font sizes at least 14pt for Pre-K-K, 13pt for 1st-2nd,
12pt for 3rd-4th, 11pt for 5th-6th, including small captions. Do not fill the sheet with tiny text.
Do not invent reading-level certifications, book-series numbers or grade claims.
No exact-count, hidden-object, maze, matching-by-tiny-feature or difference answers may depend on AI art.
If an activity needs a precise picture feature, use an exact visual or change to an open-ended task.
No teacher guide, teaching tips, answer page, or teacher instructions in this fragment.'''


def density_guidance(config: dict) -> str:
    """Budget initial reading pages without truncating authored content or changing tasks."""
    floor = config.get('minimum_text_pt',config.get('student_font_pt',11))
    if floor>=14:
        reading = 'Use picture-led tasks, no independent reading passage, and one or two brief adult-read actions.'
    else:
        words = 60 if floor>=13 else 90 if floor>=12 else 120
        workspace = 50 if floor>=13 else 65 if floor>=12 else 80
        reading = (f'For a page combining a passage and a large illustration, aim for at most {words} '
                   f'passage words, one or two short questions, and about {workspace}mm total response '
                   'space. Use a shorter passage or split the learning sequence across planned activities '
                   'if more writing space is needed; preserve the actual task and facts.')
    return (reading+' Reserve roughly 100mm vertical space for lower-grade main artwork (less for '
            'upper grades), plus the heading, prompts, borders and margins. Avoid filling every '
            'field to its individual maximum. These are planning targets; final readable print '
            'bounds, useful visual area and required response-space checks remain mandatory.')


def generate_creative_pack(theme: str, grade_band: str, grade_config: dict, *, source_context: str | None = None) -> dict:
    """Plan a varied pack, then author and print-check each original page independently."""
    config = grade_config[grade_band]
    count, font = config['activity_pages'], config['student_font_pt']
    plan_prompt = f'''Design an ORIGINAL illustrated classroom activity pack for {grade_band}.
Theme/context: {theme}. User description/inspiration: {source_context or 'Invent a fresh engaging learning experience.'}
Grade guidance: {config['skill_notes']}. Art style: {config['illustration_style']}.
Creative variation seed: {uuid4().hex[:8]} (do not print this).
You choose the exercise mechanics and page compositions; there is NO fixed menu of task types.
Create {count} distinct activities that build different ways of thinking around the actual context.
Avoid a repetitive sequence of generic counting/matching/sorting sheets. Mix appropriate
observation, invention, investigation, visual reasoning and hands-on responses when useful.
Do not simply rename the same exercise on each page. No more than two pages may share a layout.
Pre-K-K: picture-led, minimal adult-read wording, big objects, cheerful rich color and clear actions.
1st-2nd: vivid meaningful illustrations, playful compositions, short reading and response spaces.
3rd-4th: engaging visual puzzles, comics, maps or investigations where suitable; age-respectful color.
5th-6th: sophisticated visuals, restrained palette, meaningful constraints and deeper reasoning.
These are suggestions, NOT a checklist to repeat in each pack. Plan original compositions.
Images must convey task meaning, not merely decorate a header. Aim for images/visual workspace
to dominate lower-grade student pages. Keep white response areas practical for printing.
Honor the user's specific subject and description; treat reference links only as inspiration.
No copying commercial artwork/wording/characters, invented facts, stereotypes or standards claims.
Return JSON: title <=80 chars, overview <=350, art_direction <=650 (specific palette and cohesive
rendering style only, no character or scene instructions), character_description <=350 (original cast, or object design language),
cover_brief <=800, pages exactly {count}: each title <=80, learning_goal <=650,
activity_concept <=650, layout_brief <=650, render_mode and mechanic.
render_mode is exact or authored. For exact choose mechanic maze/sort/differences/pattern/matching/balance/count.
Every pages item MUST include its own top-level render_mode string and mechanic string,
alongside title, learning_goal, activity_concept and layout_brief. Do not omit these fields or
put them only inside an exercise object. Write "render_mode":"exact" or "render_mode":"authored",
never the literal combined string "exact or authored", a list, null, or a boolean.
Exact balance compares sizes, not weight. These tools support only circle,square,triangle,star,leaf,pumpkin,ghost,bat.
For any other creative exercise use authored with an ORIGINAL short mechanism label describing its actual action.
Authored tasks allow original design, investigation, craft, reading/writing or reasoning rather than a fixed menu.
Favor context-specific authored invention for at least half the pages unless the requested subject requires exact puzzles.
Closed-answer tasks cannot depend on precise AI picture features. Use exact for counts, mazes, shadow matching,
patterns and differences; use authored for open responses or supplied text/math questions. Avoid generic
reflection repeated after every puzzle. For exact puzzles, repeat the same tool AND learning goal
at most twice. Authored pages can share drawing/coloring/craft labels when their actual concepts
and compositions differ meaningfully. Use render_mode authored for these open creative tasks,
not exact. Canonical names for the exact tools are listed above. No teacher guide.'''
    plan_prompt += '\nFor shadow matching use mechanic="matching" with mechanic_constraints={"mode":"shadow"}; never use mechanic="shadows".'
    plan_prompt += ('\nmechanic_constraints is optional: matching may specify ONLY mode=shadow/identical; '
                    'sort may specify ONLY attribute=shape/color/size. For maze/count/balance/pattern/'
                    'differences and authored tasks OMIT mechanic_constraints. Never add mode or attribute '
                    'from another tool. Retain these choices consistently in the subsequent page brief.')
    plan_prompt += '\nPer-page content budget: '+density_guidance(config)
    from core.response_schemas import plan_schema, design_schema
    plan = ask_json(plan_prompt, lambda raw: validate_plan(raw, count, require_coherent=True),
                    'Creative plan', 6000, response_schema=plan_schema(count))
    context = json.dumps({k: plan[k] for k in ('title', 'art_direction', 'character_description')})
    def design_unit(number):
        """Author one independent page while preserving caller-owned page numbering."""
        if number == 0:
            return ask_json(f'Create an illustrated cover for {grade_band}. {context}\n{plan["cover_brief"]}\n'
                     + layout_contract(font, config.get('minimum_text_pt', 11), cover=True) + '\nThis is the cover: omit student tasks and answers. Include the pack title and grade. '
                     'Python places the REAL store logo in a separate 41mm header above your content. '
                     'Do not draw a logo or repeat the store name. Override the full-page height: '
                     'YOUR cover fragment must be at most 215mm high; aim for 205mm including all spacing.',
                     lambda raw: validate_design(raw, font, cover=True, quality=config), 'Cover design',
                     response_schema=design_schema(cover=True))
        brief = plan['pages'][number - 1]
        prompt = (f'Author student activity {number} for {grade_band}. Theme: {theme}. '
                  f'User context: {source_context or theme}. Skills: {config["skill_notes"]}.\n'
                  f'Art direction: {context}\nThis page brief: {json.dumps(brief)}\n'
                  f'Maximum question/action count on this page: {config.get("items_per_page",4)}.\n'
                  + density_guidance(config)+'\n'
                  f'Other planned layouts (make this page distinct): {json.dumps([p["layout_brief"] for p in plan["pages"]])}\n'
                  + layout_contract(font, config.get('minimum_text_pt', 11), coherent=True) + f'\nThe title slot will print: {brief["title"]}.')
        page = ask_json(prompt, lambda raw: validate_design(raw, font, quality=config, expected_title=brief['title'], require_coherent=True, brief=brief), f'Activity design {number}',
                        response_schema=design_schema(brief,config))
        page = compact_answers(page, number)
        page.update(title=brief['title'], page_number=number)
        LOGGER.info('Activity design %s/%s complete', number, count)
        return page
    requested_workers = int_setting('DESIGN_WORKERS', 3, 1, 4)
    workers = text_worker_limit(requested_workers)
    if workers != requested_workers:
        LOGGER.info('Design workers capped from %s to %s by configured text credential capacity',
                    requested_workers, workers)
    designs = ordered_parallel(design_unit, range(count + 1), workers)
    cover, pages = designs[0], designs[1:]
    pack = dict(title=plan['title'], overview=plan['overview'], theme=theme, grade_band=grade_band,
                character_description=plan['character_description'], art_direction=plan['art_direction'],
                resource_type='activity_pack', design_engine='creative_bound_v2', cover=cover, pages=pages)
    def repair_content(number, previous, issues):
        """Correct only the affected activity, preserving the pack's title and style."""
        source = {k: previous[k] for k in ('images','exercise')}
        source['html'] = previous['source_layout']
        source['original_answer_conditions'] = previous.get('answer_key_original')
        brief = previous['planned_intent']
        repaired = ask_json(
            f'Repair activity {number} for {grade_band}. Exact title: {previous["title"]}. '
            f'Correct these concrete exercise defects: {json.dumps(issues)}. '
            'Preserve the learning goal, meaningful visuals and response space. Return a complete page.\n'
            + layout_contract(font, config.get('minimum_text_pt', 11), coherent=True) + '\nPlanned brief: ' + json.dumps(brief) + '\nPrevious shared specification/layout: ' + json.dumps(source),
            lambda raw: validate_design(raw, font, quality=config, expected_title=previous['title'], require_coherent=True, brief=brief),
            f'Exercise repair {number}', 6500, response_schema=design_schema(brief,config))
        repaired = compact_answers(repaired, number)
        repaired.update(title=previous['title'], page_number=number)
        if previous.get('answer_key_original'):
            repaired['answer_key_original'] = previous['answer_key_original']
        return repaired
    def ask_audit(prompt, validate, label, tokens=4000):
        """Constrain proofreading output separately from the design response schema."""
        from core.response_schemas import audit_schema
        return ask_json(prompt,validate,label,tokens,response_schema=audit_schema(count))
    proofread_pack(pack, ask_audit, repair_content)
    try:
        preflight_pack(pack, config)
    except ValueError as exc:
        if not str(exc).startswith('Final answer sheet cannot fit'):
            raise
        compact_shared_answers(pack,config)
        proofread_pack(pack, ask_audit, repair_content)
        preflight_pack(pack,config)
    return pack


def generate_creative_images(pack: dict, config: dict, folder) -> None:
    """Generate assets once and check file integrity locally before PDF assembly."""
    from core.image_review import validate_image_files
    started = time.monotonic()
    assets = [a for page in [pack['cover'], *pack['pages']] for a in page['images']]
    unique, indexes = [], {}
    for page in [pack['cover'], *pack['pages']]:
        for asset in page['images']:
            if asset['prompt'] not in indexes:
                indexes[asset['prompt']] = len(unique)
                unique.append({'page_number': len(unique) + 1, 'image_prompt': asset['prompt']})
    image_pack = dict(pack, pages=unique)
    styles = dict(config, illustration_style=pack['art_direction'])
    paths = generate_images(image_pack, styles, folder) if unique else []
    if len(paths) != len(unique):
        raise ValueError('Incomplete creative illustration set')
    LOGGER.info('Image generation complete: %s unique illustrations in %.1fs', len(paths), time.monotonic() - started)
    pack['image_validation'] = validate_image_files(paths, len(unique))
    pack['image_review'] = {'status': 'disabled', 'checked': 0, 'regenerated': 0}
    LOGGER.info('Illustration files valid: %s; AI image review disabled', len(paths))
    for asset in assets:
        asset['path'] = str(paths[indexes[asset['prompt']]])


def strip_creative_art(pack: dict) -> None:
    """Remove temporary illustration paths after their bytes are embedded in the PDF."""
    for page in [pack['cover'], *pack['pages']]:
        for asset in page['images']:
            asset.pop('path', None)
