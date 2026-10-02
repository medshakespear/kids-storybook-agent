"""Let the language model author activity concepts and layouts, not fill fixed worksheets."""
from __future__ import annotations

import json
import logging
import random
import re
import time
from copy import deepcopy
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
    """Unwrap optional Markdown fences without guessing or rewriting malformed JSON."""
    value = content.strip()
    if value.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```', value, re.I)
        if match:
            value = match[1]
    return json.loads(value)


def ask_json(prompt: str, validate, label: str, tokens: int = 6000) -> dict:
    """Retry validation defects separately from transient provider transport failures."""
    errors = []
    floor_match = re.search(r'Minimum student font: (\d+)pt', prompt)
    minimum_font = int(floor_match[1]) if floor_match else 11
    messages = [
        {'role': 'system', 'content': (
            'You are an original elementary curriculum designer and print art director. '
            'Return valid JSON only. Use single quotes for HTML attribute values inside JSON strings; '
            'escape any embedded double quotes and line breaks. No trailing commas or Markdown fences.'
        )},
        {'role': 'user', 'content': prompt},
    ]
    max_validation_attempts = 3
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
                try:
                    LOGGER.info('%s: %s / %s attempt %s', label, provider, model,
                                validation_attempt + 1)
                    response = api.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_format={'type': 'json_object'},
                        temperature=0.3 if len(messages) > 2 else 0.8,
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
                    result = validate(parse_design_json(content))
                    return result
                except (ValueError, TypeError, KeyError, IndexError) as exc:
                    validation_attempt += 1
                    transport_failures = 0
                    reason = f'{label}: {provider}: {exc}'
                    errors.append(reason)
                    LOGGER.warning('%s', reason)
                    if validation_attempt >= max_validation_attempts:
                        break

                    # Keep only the latest draft/correction instead of an expanding conversation.
                    messages = messages[:2]
                    if content:
                        messages.append({'role': 'assistant', 'content': content[:36000]})
                    repair = f'Correct only this unit and return complete JSON. Validation: {exc}'
                    if isinstance(exc, json.JSONDecodeError):
                        repair += (
                            ' Repair JSON serialization only: check missing commas, unescaped double quotes '
                            'inside the html string, and literal line breaks. Use single-quoted HTML attributes. '
                            'Preserve the exercise and design rather than inventing a different page.'
                        )
                    asset_error = str(exc).lower()
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
                            'required exercise content' in asset_error):
                        repair += (
                            ' Repair content binding only, not the activity. Return html, images, exercise. '
                            'All task wording belongs in exercise.directions, passage or questions[].prompt; '
                            'For a contextual heading or illustration label, preserve its wording in '
                            'exercise.captions [{id:"context",text:"original label"}] and replace the raw '
                            'HTML text with an empty data-content="caption_context" slot. Use child-friendly '
                            'vocabulary for younger grades; do not move instructions or solutions into captions. '
                            'Retain existing correct wording and answer/criterion. Layout containers '
                            'use data-content="title", "directions", "passage", "name", "caption_ID" or "question_ID". '
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
                    if ('visual question' in asset_error or 'visual needs' in asset_error or
                            'visual ids' in asset_error or 'data-visual' in asset_error or
                            'visuals must' in asset_error):
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
    for page in plan['pages']:
        if not isinstance(page, dict):
            raise ValueError('Each planned page must be an object')
        for key in ('title', 'learning_goal', 'activity_concept', 'layout_brief'):
            page[key] = _text(page.get(key), key, 80 if key == 'title' else 650)
        page['title'] = _text(activity_title(page['title']), 'activity title without page label', 80)
        if require_coherent: validate_brief(page,planning=True)
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
Exact balance compares sizes, not weight. These tools support only circle,square,triangle,star,leaf,pumpkin,ghost,bat.
For any other creative exercise use authored with an ORIGINAL short mechanism label describing its actual action.
Authored tasks allow original design, investigation, craft, reading/writing or reasoning rather than a fixed menu.
Favor context-specific authored invention for at least half the pages unless the requested subject requires exact puzzles.
Closed-answer tasks cannot depend on precise AI picture features. Use exact for counts, mazes, shadows,
patterns and differences; use authored for open responses or supplied text/math questions. Avoid generic
reflection repeated after every puzzle. For exact puzzles, repeat the same tool AND learning goal
at most twice. Authored pages can share drawing/coloring/craft labels when their actual concepts
and compositions differ meaningfully. Use render_mode authored for these open creative tasks,
not exact. Canonical names for the exact tools are listed above. No teacher guide.'''
    plan = ask_json(plan_prompt, lambda raw: validate_plan(raw, count, require_coherent=True), 'Creative plan', 6000)
    context = json.dumps({k: plan[k] for k in ('title', 'art_direction', 'character_description')})
    def design_unit(number):
        """Author one independent page while preserving caller-owned page numbering."""
        if number == 0:
            return ask_json(f'Create an illustrated cover for {grade_band}. {context}\n{plan["cover_brief"]}\n'
                     + layout_contract(font, config.get('minimum_text_pt', 11), cover=True) + '\nThis is the cover: omit student tasks and answers. Include the pack title and grade. '
                     'Python places the REAL store logo in a separate 41mm header above your content. '
                     'Do not draw a logo or repeat the store name. Override the full-page height: '
                     'YOUR cover fragment must be at most 215mm high; aim for 205mm including all spacing.',
                     lambda raw: validate_design(raw, font, cover=True, quality=config), 'Cover design')
        brief = plan['pages'][number - 1]
        prompt = (f'Author student activity {number} for {grade_band}. Theme: {theme}. '
                  f'User context: {source_context or theme}. Skills: {config["skill_notes"]}.\n'
                  f'Art direction: {context}\nThis page brief: {json.dumps(brief)}\n'
                  f'Maximum question/action count on this page: {config.get("items_per_page",4)}.\n'
                  f'Other planned layouts (make this page distinct): {json.dumps([p["layout_brief"] for p in plan["pages"]])}\n'
                  + layout_contract(font, config.get('minimum_text_pt', 11), coherent=True) + f'\nThe title slot will print: {brief["title"]}.')
        page = ask_json(prompt, lambda raw: validate_design(raw, font, quality=config, expected_title=brief['title'], require_coherent=True, brief=brief), f'Activity design {number}')
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
            f'Exercise repair {number}', 6500)
        repaired = compact_answers(repaired, number)
        repaired.update(title=previous['title'], page_number=number)
        if previous.get('answer_key_original'):
            repaired['answer_key_original'] = previous['answer_key_original']
        return repaired
    proofread_pack(pack, ask_json, repair_content)
    try:
        preflight_pack(pack, config)
    except ValueError as exc:
        if not str(exc).startswith('Final answer sheet cannot fit'):
            raise
        compact_shared_answers(pack,config)
        proofread_pack(pack, ask_json, repair_content)
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
