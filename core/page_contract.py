"""Bind creative layouts to one exercise specification, with no parallel answer draft."""
from __future__ import annotations

import html
import re
from collections import Counter
from copy import deepcopy
from html.parser import HTMLParser

from core.print_tags import TAG_ALIASES
from core.content_binding import bind_formatted_canonical_text, bind_standard_heading
from core.task_visuals import normalize_visual_metadata, page_visuals

EXACT_MECHANICS = {'maze', 'sort', 'differences', 'pattern', 'matching', 'balance', 'count'}


EXACT_ALIASES = {
    'counting':('count',{}), 'picture_counting':('count',{}), 'count_objects':('count',{}),
    'sorting':('sort',{}), 'picture_sorting':('sort',{}),
    'shape_sorting':('sort',{'attribute':'shape'}), 'color_sorting':('sort',{'attribute':'color'}),
    'size_sorting':('sort',{'attribute':'size'}),
    'patterns':('pattern',{}), 'pattern_completion':('pattern',{}), 'repeating_pattern':('pattern',{}),
    'complete_pattern':('pattern',{}), 'picture_matching':('matching',{}),
    'shadow_matching':('matching',{'mode':'shadow'}), 'identical_matching':('matching',{'mode':'identical'}),
    'spot_the_difference':('differences',{}), 'spot_the_differences':('differences',{}),
    'find_differences':('differences',{}), 'size_comparison':('balance',{}),
    'size_comparisons':('balance',{}), 'compare_sizes':('balance',{}), 'mazes':('maze',{}),
}
OPEN_MECHANICS = {'drawing','coloring','colouring','craft','crafting','collage','color_and_draw',
                  'draw_and_color','design','design_challenge','invention','reflection','discussion',
                  'role_play','storytelling','creative_writing','pattern_creation','create_pattern'}


def canonical_mechanic(value: str) -> tuple[str, dict]:
    """Normalize explicit tool aliases while retaining their declared sorting/matching rules."""
    name = re.sub(r'[\s-]+','_',value.strip().casefold())
    kind,constraints = EXACT_ALIASES.get(name,(name,{}))
    return kind,dict(constraints)


def bounded_text(value, name: str, limit: int, *, optional: bool = False) -> str:
    """Validate readable content without interpreting it as HTML or executable code."""
    if value is None and optional:
        return ''
    if not isinstance(value, str) or len(value.strip()) > limit or (not optional and not value.strip()):
        raise ValueError(f'Exercise {name} must be {"optional " if optional else "nonempty "}text <= {limit} characters')
    return value.strip()


class BoundLayout(HTMLParser):
    """Fill named content slots while rejecting independent directions or answers."""

    def __init__(self, blocks: dict[str, str]):
        """Track placeholder ownership and references in an authored layout."""
        super().__init__(convert_charrefs=True)
        self.blocks, self.used, self.parts, self.stack = blocks, set(), [], []
        self.slot = None
        self.slot_nesting = []
        self.inferred_slot = False
        self.assets, self.visuals = [], []
        self.visual_styles = {}
        self.text_blocks = {}
        for key,value in blocks.items():
            parser = HTMLParser(convert_charrefs=True)
            words = []
            parser.handle_data = words.append
            parser.feed(value)
            self.text_blocks[key] = ' '.join(' '.join(words).split()).casefold()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Replace empty content placeholders and preserve design-only wrappers."""
        tag = TAG_ALIASES.get(tag,tag)
        if self.slot:
            if self.inferred_slot:
                raise ValueError('Bind this entire text container with data-content; do not append independent formatting or wording to an inferred content slot')
            # A prefilled slot is only a redundant model draft: canonical text
            # replaces it. Never discard task graphics or another content slot.
            if tag not in {'p','div','section','span','strong','b','em','br'} or any(
                    key in {'data-content','data-asset','data-visual','src'} for key,_ in attrs):
                raise ValueError('Prefilled content slots may contain only text/formatting; keep graphics and other slots outside them')
            if tag != 'br': self.slot_nesting.append(tag)
            return
        data = dict(attrs)
        if len(data) != len(attrs):
            raise ValueError('Duplicate layout attributes')
        block = data.pop('data-content', None)
        if block is not None:
            if tag not in {'h1','h2','h3','h4','h5','h6','p','div','span','section','td','th','li','strong','b','em'}:
                raise ValueError('Use a text container for data-content slots')
            if block not in self.blocks or block in self.used:
                raise ValueError(f'Unknown or repeated exercise content slot: {block}')
            self.used.add(block)
            self.slot = block
            self.inferred_slot = False
        attributes = ' '.join(f'{key}="{html.escape(value or "", quote=True)}"' for key,value in data.items())
        self.parts.append(f'<{tag} {attributes}>')
        if block:
            self.parts.append(self.blocks[block])
        if tag == 'img':
            if data.get('data-asset'): self.assets.append(data['data-asset'])
            if data.get('data-visual'):
                self.visuals.append(data['data-visual'])
                self.visual_styles[data['data-visual']] = data.get('style','')
        if tag not in {'img','br'}:
            self.stack.append((tag,block))

    def handle_endtag(self, tag: str) -> None:
        """Require correctly nested wrappers and close filled content slots."""
        tag = TAG_ALIASES.get(tag,tag)
        if self.slot and self.slot_nesting:
            if self.slot_nesting[-1] != tag:
                raise ValueError('Prefilled content slot formatting must be balanced')
            self.slot_nesting.pop()
            return
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError('Exercise layout tags must be balanced')
        _,block = self.stack.pop()
        if block:
            self.slot = None
            self.inferred_slot = False
        self.parts.append(f'</{tag}>')

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Support ordinary self-closing artwork, breaks and empty content slots."""
        self.handle_starttag(tag,attrs)
        if TAG_ALIASES.get(tag,tag) not in {'img','br'}: self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        """Replace slot drafts and bind exact canonical copies without accepting unrelated tasks."""
        if not data.strip():
            return
        if self.slot:
            if self.inferred_slot:
                raise ValueError('Use a complete data-content slot; additional independent layout text cannot be discarded')
            return
        normalized = ' '.join(data.split()).casefold()
        matches = [key for key,value in self.text_blocks.items() if normalized==value]
        if not matches:
            matches = [key for key,value in self.text_blocks.items() if key.startswith('question_')
                       and re.sub(r'^\d+[a-z]?\.\s*','',value)==normalized]
        if not matches and self.stack and self.stack[-1][0] in {'h1','h2','h3','h4'}:
            heading = re.sub(r'^(?:page|activity)\s+#?\d+\s*[:.\-–—]\s*','',normalized)
            if heading==self.text_blocks['title']: matches = ['title']
        if not matches and re.fullmatch(r'name\s*:\s*[_\s]*',normalized):
            matches = ['name']
        if len(matches)==1:
            key = matches[0]
            if key in self.used:
                return  # Do not print a second copy of an already bound instruction.
            if self.stack and self.stack[-1][0] in {'h1','h2','h3','h4','h5','h6','p','div','span','section','td','th','li','strong','b','em'}:
                tag,_ = self.stack[-1]
                self.stack[-1] = (tag,key)
                self.used.add(key)
                self.slot = key
                self.inferred_slot = True
                self.parts.append(self.blocks[key])
                return
        raise ValueError('Put ALL printed wording in exercise fields and data-content slots; '
                         f'unbound wording: {data.strip()[:100]!r}. Preserve the task and bind this '
                         'wording to the appropriate directions, passage or question field')

    def handle_comment(self, data: str) -> None:
        """Reject hidden duplicate instruction drafts in layout comments."""
        raise ValueError('Do not put content or comments in the exercise layout')


def validate_brief(page: dict, *, planning: bool = False) -> None:
    """Normalize concrete mechanics without turning unsupported closed puzzles into AI guesses."""
    mode = page.get('render_mode')
    mode = mode.strip().casefold() if isinstance(mode,str) else mode
    if mode not in {'exact','authored'}:
        raise ValueError('Each page needs render_mode exact or authored')
    original = bounded_text(page.get('mechanic'),'mechanic',50)
    kind,constraints = canonical_mechanic(original)
    if mode=='exact' and kind not in EXACT_MECHANICS:
        complete_open_task = bool(page.get('directions')) and isinstance(page.get('questions'),list) and bool(page['questions'])
        if kind in OPEN_MECHANICS and not page.get('visual') and (planning or complete_open_task):
            mode = 'authored'  # This changes a mislabeled mode, never the proposed creative task.
        else:
            raise ValueError(f'Unsupported exact mechanic {original!r}. Exact tools are {sorted(EXACT_MECHANICS)}; '
                             'use authored for an open drawing, craft, writing or other original task. '
                             'Do not turn an unsupported closed-answer puzzle into an illustrative AI picture')
    page['render_mode'] = mode
    if mode=='exact':
        previous = page.get('mechanic_constraints',{})
        if not isinstance(previous,dict) or set(previous)-{'mode','attribute'}:
            raise ValueError('Exact mechanic constraints may specify only matching mode or sorting attribute')
        allowed = {'matching': {'mode': {'shadow','identical'}},
                   'sort': {'attribute': {'shape','color','size'}}}.get(kind,{})
        if any(key not in allowed or not isinstance(value,str) or value not in allowed[key]
               for key,value in previous.items()):
            raise ValueError('Exact mechanic constraints must match the selected tool and its supported rules')
        if any(key in previous and previous[key]!=value for key,value in constraints.items()):
            raise ValueError('Exact mechanic alias contradicts its declared matching/sorting rule')
        page['mechanic'] = kind
        if constraints or previous: page['mechanic_constraints'] = {**previous,**constraints}
    else:
        page['mechanic'] = ' '.join(original.split()).casefold()


def normalize_illustration_ids(page: dict) -> None:
    """Normalize only equivalent asset spellings; never guess between different subjects."""
    images = page.get('images')
    exercise = page.get('exercise')
    if (images is None and isinstance(exercise,dict)
            and str(exercise.get('render_mode','')).strip().casefold()=='exact'
            and isinstance(exercise.get('visual'),dict)
            and not re.search(r'\bdata-asset\s*=',page.get('html',''),re.I)):
        images = []  # An already authored precise graphic needs no invented raster art.
    if isinstance(images,dict) and {'id','prompt'} & set(images) and set(images)!={'id','prompt'}:
        raise ValueError('Illustration manifest singleton must contain exactly id and prompt; do not mix image fields with a keyed image map')
    if isinstance(images,dict) and set(images)=={'id','prompt'}:
        images = [images]  # An explicitly authored singleton, not missing artwork.
    elif isinstance(images,dict) and images and all(isinstance(k,str) for k in images):
        entries = []
        for key,value in images.items():
            if isinstance(value,str) and value.strip():
                entries.append({'id':key,'prompt':value})
            elif isinstance(value,dict) and set(value)<= {'id','prompt'} and isinstance(value.get('prompt'),str) and value['prompt'].strip():
                if 'id' in value and value['id']!=key:
                    raise ValueError('Illustration manifest map key contradicts its declared image id')
                entries.append({'id':key,'prompt':value['prompt']})
            else:
                raise ValueError('Illustration manifest images must be a JSON list of explicit id/prompt objects')
        images = entries
    if not isinstance(images,list):
        raise ValueError(f'Illustration manifest images must be a JSON list; received {type(images).__name__}. '
                         'Supply explicit id/prompt objects and matching HTML data-asset references')
    page['images'] = images
    declared = set()
    for asset in images:
        original = asset.get('id') if isinstance(asset,dict) else None
        if not isinstance(original,str):
            raise ValueError('Illustration IDs must be short lowercase text identifiers')
        normalized = re.sub(r'[\s-]+','_',original.strip().casefold())
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,30}',normalized):
            raise ValueError(f'Illustration ID {original!r} must be a short lowercase identifier')
        if normalized in declared:
            raise ValueError(f'Illustration IDs collide after normalization: {normalized!r}; keep distinct purposeful subjects under distinct IDs')
        declared.add(normalized)
        asset['id'] = normalized

    def replace(match):
        """Update a quoted or unquoted HTML reference only for its equivalent declared ID."""
        value = html.unescape(match[2] if match[2] is not None else match[3] if match[3] is not None else match[4])
        normalized = re.sub(r'[\s-]+','_',value.strip().casefold())
        if normalized not in declared:
            return match[0]
        return match[1]+'"'+normalized+'"'

    page['html'] = re.sub(r'''(\bdata-asset\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s>]+))''',
                          replace,page['html'],flags=re.I)


def compile_exercise(page: dict, config: dict, title: str, brief: dict | None = None) -> None:
    """Build printed tasks, calculation checks and answer key from the same data."""
    if any(page.get(k) for k in ('answers','visuals','calculations')):
        raise ValueError('Use only the shared exercise specification, not independent answers/visuals/calculations drafts')
    normalize_illustration_ids(page)
    exercise = deepcopy(page.get('exercise'))
    if not isinstance(exercise, dict):
        raise ValueError('Return exercise as the shared source of task content, visuals and answers')
    validate_brief(exercise)
    if brief and any(exercise.get(k) != brief.get(k) for k in ('render_mode','mechanic')):
        raise ValueError('Preserve the planned render_mode and mechanic; do not replace this exercise with a different puzzle')
    exercise['goal'] = bounded_text(exercise.get('goal'), 'goal', 240)
    blocks = {'title': html.escape(title), 'name': 'Name: ____________________'}
    page['visuals'], page['calculations'] = [], []
    if exercise['render_mode'] == 'exact':
        visual = exercise.get('visual')
        if not isinstance(visual,dict) or not isinstance(visual.get('kind'),str):
            raise ValueError('Exercise visual kind must match its planned exact mechanic')
        kind,visual_constraints = canonical_mechanic(visual['kind'])
        if kind!=exercise['mechanic']:
            raise ValueError('Exercise visual kind must match its planned exact mechanic')
        visual['kind'] = kind
        constraints = {}
        for source in ((brief or {}).get('mechanic_constraints',{}),exercise.get('mechanic_constraints',{}),visual_constraints):
            for key,value in source.items():
                if key in constraints and constraints[key]!=value:
                    raise ValueError('Preserve the planned exact matching/sorting rule')
                constraints[key] = value
        for key,value in constraints.items():
            if key in visual and visual[key]!=value:
                raise ValueError('Preserve the planned exact matching/sorting rule')
            visual[key] = value
        page['visuals'] = [visual]
        normalize_visual_metadata(page)
        exercise['visual'] = page['visuals'][0]
        problems = []
        if exercise.get('directions') or exercise.get('passage'):
            problems.append('Exact visual prints its own verified directions; omit parallel directions/passage to avoid task mismatches')
        visual_question = str(exercise['visual'].get('question'))
        for index,question in enumerate(exercise.get('questions',[]) if isinstance(exercise.get('questions',[]),list) else [],1):
            if isinstance(question,dict) and str(question.get('id')).strip()==visual_question:
                problems.append(f'Exercise question IDs must not duplicate visual question numbers: questions item {index} '
                                f'uses reserved label {visual_question}. If it repeats the exact puzzle, do not author '
                                'a second question/answer about it; if it is a genuinely additional action, assign '
                                'an unused label and update its question_ID slot together')
        if problems:
            raise ValueError('; '.join(problems))
        page_visuals(page)
    else:
        if exercise.get('visual'):
            raise ValueError('Use exact mode for computed puzzle visuals; authored mode retains the creative task')
        directions = bounded_text(exercise.get('directions'), 'directions', 180 if config.get('student_font_pt',13)>=14 else 350)
        # Exact-answer questions may not assume that generated art contains precise features.
        task_text = directions + ' ' + ' '.join(str(q.get('prompt','')) for q in exercise.get('questions',[]) if isinstance(q,dict))
        art_dependency = re.search(r'\b(pictures?|illustrations?|images?|photos?|scenes?)\b',task_text,re.I)
        closed_action = re.search(r'(count|how many|match|circle|find|which).{0,60}(objects?|pictures?|shadows?|missing (piece|picture)|heavier|larger|comes next)',task_text,re.I)
        shadow_task = re.search(r'(match|draw lines).{0,50}shadows?',task_text,re.I)
        if (art_dependency and closed_action) or shadow_task:
            raise ValueError('Closed visual task needs the appropriate exact mechanic; do not infer its answer from AI artwork')
        blocks['directions'] = html.escape(directions)
        passage = bounded_text(exercise.get('passage'), 'passage', 1500, optional=True)
        if passage:
            if config.get('student_font_pt',13)>=15:
                raise ValueError('Pre-K tasks must be picture-led, not independent reading passages')
            blocks['passage'] = html.escape(passage).replace('\n','<br/>')
    page['html'] = bind_standard_heading(page['html'],exercise)
    # Context captions are canonical content too, not a second instruction draft.
    captions = exercise.get('captions', [])
    if not isinstance(captions,list) or len(captions)>6:
        raise ValueError('Exercise captions must be a list of at most six short contextual labels')
    caption_ids = set()
    for caption in captions:
        if not isinstance(caption,dict):
            raise ValueError('Exercise caption must contain id and text')
        cid = caption.get('id')
        if not isinstance(cid,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,23}',cid) or cid in caption_ids:
            raise ValueError('Caption IDs must be distinct short lowercase identifiers')
        caption_ids.add(cid)
        caption['text'] = bounded_text(caption.get('text'),f'caption {cid}',120)
        blocks['caption_'+cid] = html.escape(caption['text'])
    questions = exercise.get('questions', [])
    if not isinstance(questions,list) or len(questions)>config.get('items_per_page',4):
        raise ValueError('Exercise questions must be a short list within this grade band item limit')
    if exercise['render_mode']=='authored' and not questions:
        raise ValueError('Authored exercise needs at least one question/action and its answer or success criterion')
    reserved = {str(v['question']) for v in page['visuals']}
    answers = []
    for question in questions:
        if not isinstance(question,dict): raise ValueError('Exercise question must be an object')
        qid = question.get('id')
        if type(qid) is int: qid = str(qid)
        if not isinstance(qid,str) or not re.fullmatch(r'[1-9]\d?(?:[A-Za-z])?',qid) or qid in reserved:
            raise ValueError(f'Exercise question IDs must be distinct printed labels, e.g. 1 or 2A; '
                             f'got {qid!r}, already used/reserved {sorted(reserved)}. '
                             'Do not duplicate visual question numbers; update the question ID and question_ID slot together')
        question['id'] = qid
        reserved.add(qid)
        prompt = bounded_text(question.get('prompt'), f'question {qid} prompt', 220)
        answer = bounded_text(question.get('answer'), f'question {qid} answer/criterion', 180)
        space = question.get('space_mm',0)
        if type(space) not in {int,float} or not 0<=space<=80:
            raise ValueError('Exercise response space_mm must be 0-80; keep drawing/writing space usable')
        # Every task prompt is printed exactly once; response areas travel with their question.
        content = f'{qid}. {html.escape(prompt)}'
        if space:
            content += f'<span style="display:block;height:{space:g}mm;border:0.4mm solid #809AA6;margin-top:3mm;border-radius:3mm"></span>'
        blocks['question_'+qid] = content
        answers.append(f'{qid}. {answer}')
        calculation = question.get('calculation')
        from core.exercise_quality import numeric_display_text
        numeric_prompt = numeric_display_text(prompt)
        numeric_facts = re.findall(r'(?<![\w.])(?:\d+(?:\.\d+)?|\.\d+)(?:\s*[+−×÷*/-]\s*(?:\d+(?:\.\d+)?|\.\d+))+(?![\w.])', numeric_prompt)
        if numeric_facts and calculation is None:
            raise ValueError(f'Question {qid}: printed arithmetic requires a calculation in the shared specification')
        if calculation is not None:
            if not isinstance(calculation,dict): raise ValueError('Question calculation must contain expression and answer')
            from core.exercise_quality import calculate, normalize_calculation
            original_expression = calculation.get('expression')
            try:
                calculation['expression'] = normalize_calculation(original_expression)
            except ValueError as exc:
                raise ValueError(f'Question {qid}: calculation expression {str(original_expression)[:80]!r}: {exc}') from None
            page['calculations'].append(dict(question=qid,expression=calculation['expression'],answer=calculation.get('answer')))
            # The numeric answer printed in the key is also computed from this same object.
            actual = calculate(calculation['expression'])
            from fractions import Fraction
            try: supplied = Fraction(str(calculation.get('answer')))
            except (ValueError,ZeroDivisionError): raise ValueError('Question calculation answer must be numeric') from None
            if len(numeric_facts)==1 and not re.search(r'[()]',prompt) and calculate(numeric_facts[0])!=actual:
                raise ValueError(f'Question {qid}: calculation does not solve the printed arithmetic')
            if actual != supplied:
                raise ValueError(f'Question {qid}: declared math answer is incorrect; '
                                 f'calculation {calculation["expression"]!r} evaluates to {actual}, '
                                 f'not {supplied}. Correct calculation.answer and the shared answer key; '
                                 'preserve the printed question and verify that this operation solves it')
            # Require the prose key to contain the exact numeric answer, never an unrelated narrative.
            numeric_key = numeric_display_text(answer)
            candidates = re.findall(r'(?<![\w.])-?(?:\d+(?:\.\d+)?|\.\d+)(?:/\d+)?(?![\w.])', numeric_key)
            values = []
            for value in candidates:
                try: values.append(Fraction(value))
                except (ValueError,ZeroDivisionError): continue
            for whole,numerator,denominator in re.findall(r'(?<![\w.])(-?\d+)\s+(\d+)/(\d+)(?![\w.])',answer):
                try:
                    part = Fraction(int(numerator),int(denominator))
                    values.append(Fraction(whole)+(-part if whole.startswith('-') else part))
                except (ValueError,ZeroDivisionError): continue
            if actual not in values:
                raise ValueError(f'Question {qid}: answer key must contain its verified calculation answer')
    page['answers'] = ' '.join(answers)
    # Each answer and question count is already bounded. Check final sheet geometry
    # during pack preflight rather than imposing a contradictory aggregate character cap.
    layout = page['html']
    bound_layout = bind_formatted_canonical_text(layout,blocks)
    parser = BoundLayout(blocks)
    parser.feed(bound_layout); parser.close()
    required = set(blocks)-{'name'}
    if parser.stack or not required.issubset(parser.used):
        raise ValueError(f'Use every required exercise content slot exactly once: missing {sorted(required-parser.used)}')
    compiled_visuals = page_visuals(page)
    expected_visuals = set(compiled_visuals)
    if set(parser.visuals)!=expected_visuals or len(parser.visuals)!=len(expected_visuals):
        raise ValueError('Render the exact exercise visual once; never replace or duplicate its mechanism')
    for vid,(svg,_) in compiled_visuals.items():
        style = parser.visual_styles[vid]
        dimensions = {}
        for name,value in re.findall(r'(?:^|;)\s*(width|height)\s*:\s*([^;]+)',style):
            match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)mm',value.strip())
            if not match:
                raise ValueError('Exact visual width and height must be explicit positive mm dimensions')
            dimensions[name] = float(match[1])
        if set(dimensions)!={'width','height'}:
            raise ValueError('Exact visual width and height must be explicit positive mm dimensions')
        intrinsic_height = float(re.search(r'<svg[^>]*height="([0-9.]+)"',svg)[1])
        smallest = min(float(v) for v in re.findall(r'font-size="([0-9.]+)"',svg))
        printed_font = smallest * min(dimensions['width']/720,dimensions['height']/intrinsic_height) * 72/25.4
        if printed_font+0.05 < config.get('minimum_text_pt',11):
            raise ValueError('Exact visual labels would be too small: enlarge its width/height while preserving page fit')
    expected_assets = {a['id'] for a in page.get('images',[]) if isinstance(a,dict) and 'id' in a}
    if set(parser.assets)!=expected_assets or len(parser.assets)!=len(expected_assets):
        counts = Counter(parser.assets)
        missing = sorted(expected_assets-set(counts))
        undeclared = sorted(set(counts)-expected_assets)
        repeated = {key:value for key,value in sorted(counts.items()) if value>1}
        raise ValueError('Render every purposeful exercise illustration exactly once: '
                         f'missing HTML data-asset IDs {missing}; undeclared HTML IDs {undeclared}; '
                         f'repeated HTML IDs/counts {repeated}. Keep each purposeful image prompt and '
                         'synchronize its images[].id with exactly one img data-asset reference; '
                         'distinct subjects need distinct IDs/prompts')
    page['html'] = ''.join(parser.parts)
    page['source_layout'] = layout
    page['exercise'] = exercise
    page['exercise_binding'] = {'status':'bound','mechanic':exercise['mechanic'],
                                'render_mode':exercise['render_mode'],'question_ids':sorted(reserved)}
    if brief: page['planned_intent'] = deepcopy(brief)


EXERCISE_CONTRACT = '''Each student page returns ONLY html, images and exercise. Content and answers have
ONE shared source. goal <=240 chars, directions <=180 chars for younger grades or <=350 for older;
passage <=1500 chars (none for Pre-K). question prompt <=220 chars, answer/criterion <=180 chars;
Keep answers concise without dropping solutions or success criteria; there is no combined character cap.
Python checks actual final answer-sheet fit, not an arbitrary per-page aggregate length. exercise: {render_mode, mechanic, goal, directions?, passage?, captions?:[{id,text}], visual?, questions:[]}.
Preserve render_mode and mechanic from the planned brief. Do not substitute sorting for balancing,
matching for mazes, or a maze for completing a pattern. If the chosen task cannot be rendered, repair
THIS task rather than replacing it with another mechanism.
- exact: visual contains ONE exact component with kind=mechanic. Omit directions and passage;
  Python prints the computed task directions inside that graphic. Include the graphic once via img
  data-visual. questions may contain related optional actions with DIFFERENT IDs; no duplicated
  directions or answers about the exact visual. Do not return a parallel top-level visuals list.
  Default exact page: questions:[], NO directions/passage and NO directions/passage/question slots.
  visual.question=1 owns printed task 1 AND its computed answer. It is NOT a questions[] item.
  For a genuinely additional open action use id:"2" (or another unused label) and question_2.
  Context belongs in the title or a short non-instruction caption, not invented puzzle directions.
  Counting graphics ask students to count and WRITE each row's total; do not add connecting/matching
  directions to a count graphic. Matching, sort, patterns and other tools likewise print their own action.
  No independent instruction paragraphs before or after the exact graphic.
- authored: Gemini invents the complete original creative task: craft, coloring, role-play planning,
  reading, writing, mathematical reasoning or another age-appropriate mechanism; not a fixed menu.
  directions is the single concise task instruction, passage optional. Questions are required.
Each questions item: {id:"1", prompt:"Draw a safe costume.", answer:"Accept an original safe design.",
space_mm:50, calculation?:{expression:"20-8",answer:12}}. IDs are distinct printed task labels.
answer is a correct solution or a concrete success criterion for an open activity. Any arithmetic
question includes calculation.expression as a numeric computation such as "20-8", "12.50+7.25"
or "200*15/100". No variables, equals signs, function calls, units, powers or wording in expression.
For a missing-number equation x+8=20 printed in the prompt, expression is "20-8", not "x+8=20".
Never use a variable name or verbal formula such as "total_cost" as expression. calculation.answer
is its final numeric value or fraction string; its prose answer must contain that same numeric result. Do not put
answers in student prompts. For exact mode do not repeat the graphic's computed answer in questions.
HTML is a freely designed layout with EMPTY data-content slots. ALL printed wording comes from
exercise fields. Required title slot: <h1 data-content="title"></h1>; optional name slot:
<p data-content="name"></p>. Authored directions slot: <p data-content="directions"></p>.
Passage, if provided: <div data-content="passage"></div>. Context headings or picture labels use
exercise.captions: [{id:"context",text:"Plants growing together"}] (optional, at most 6; each text
<=120 chars). Print each once with <p data-content="caption_context"></p>. Keep captions factual,
grade-appropriate and short. Instructions and questions still belong in their own fields, never in
captions; captions do not supply answers. Each question needs exactly one slot:
<div data-content="question_1"></div>. Python fills prompt, number and response space together.
Use ordinary div/section/table/panels, inline styles and images to invent original compositions.
Do not put independent text, numbers, labels, comments or task instructions in html. Do not fill
slots yourself; redundant filled drafts are replaced by canonical exercise wording. Never return a separate answers/calculations draft: Python derives both from exercise.
Artwork supports task context or open-ended creation. Closed answers must not require identifying
exact pixels, hidden objects, missing costume pieces, specific faces or counting AI-generated objects.
For lower grades use a large useful illustration, expressive craft/coloring material or a large exact
visual; avoid mascot thumbnails. Use few short adult-read directions and ample physical response space.
'''
