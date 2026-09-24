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
from core.creative_layout import check_page, preflight_pack, PROPERTIES, TAGS
from core.image_generator import generate_images
from core.providers import text_provider_names, text_client, text_worker_limit, safe_api_error
from core.runtime import int_setting, ordered_parallel

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
    """Retry one bounded creative unit with its previous draft; preserve completed pages."""
    errors, messages = [], [{'role': 'system', 'content': 'You are an original elementary curriculum designer and print art director. Return valid JSON only. Use single quotes for HTML attribute values inside JSON strings; escape any embedded double quotes and line breaks. No trailing commas or Markdown fences.'}, {'role': 'user', 'content': prompt}]
    for provider in text_provider_names():
        api, model = text_client(provider)
        try:
            for attempt in range(3):
                content = None
                try:
                    LOGGER.info('%s: %s / %s attempt %s', label, provider, model, attempt + 1)
                    response = api.chat.completions.create(model=model, messages=messages,
                        response_format={'type': 'json_object'}, temperature=0.3 if len(messages) > 2 else 0.8,
                        max_completion_tokens=tokens)
                    content = response.choices[0].message.content
                    if not content:
                        raise ValueError('Empty design response')
                    if getattr(response.choices[0], 'finish_reason', None) == 'length':
                        raise ValueError('Response was truncated by the token limit; return a shorter complete design with concise markup')
                    return validate(parse_design_json(content))
                except (ValueError, TypeError, KeyError, IndexError) as exc:
                    reason = f'{label}: {provider}: {exc}'
                    errors.append(reason)
                    LOGGER.warning('%s', reason)
                    # Keep only the latest draft/correction instead of an expanding conversation.
                    messages = messages[:2]
                    if content:
                        messages.append({'role': 'assistant', 'content': content[:36000]})
                    repair = f'Correct only this unit and return complete JSON. Validation: {exc}'
                    if isinstance(exc, json.JSONDecodeError):
                        repair += (' Repair JSON serialization only: check missing commas, unescaped double quotes '
                                   'inside the html string, and literal line breaks. Use single-quoted HTML attributes. '
                                   'Preserve the exercise and design rather than inventing a different page.')
                    asset_error = str(exc).lower()
                    if ('illustration' in asset_error or 'data-asset' in asset_error or
                            'asset mismatch' in asset_error):
                        repair += (
                            ' Repair the image manifest and HTML together. Return images as a JSON list of 1-4 '
                            'objects, each exactly {"id":"short_lowercase_id","prompt":"complete visual prompt"}. '
                            'Every <img> in html must use data-asset with EXACTLY one of those declared IDs. '
                            'Every declared image ID must appear in html at least once. Do not use src attributes. '
                            'Do not rename an ID on only one side: synchronize images[].id and every data-asset '
                            'reference in the same response. Keep the existing activity content and layout.'
                        )
                        if label == 'Cover design':
                            repair += (
                                ' This is a COVER: keep at least one purposeful illustration and place it visibly '
                                'in the cover HTML with <img data-asset=...>. Do not solve the mismatch by deleting '
                                'the image element or returning an unused images entry.'
                            )
                    if 'overflow' in asset_error or 'printable bounds' in asset_error:
                        repair += (' Recompose this same activity more compactly. Budget at most 245mm of content '
                                   'height including headings, margins, borders and response spaces. Keep total '
                                   'table widths including cell padding and spacing below 186mm. Avoid explicit '
                                   'percentage widths on table cells; use equal auto-width cells or a stacked layout. '
                                   'Do not hide overflow, remove questions, shrink text below 11pt or remove essential response space.')
                        if label == 'Cover design':
                            repair += ' The cover also reserves 41mm for the real store logo: keep YOUR fragment below 215mm, ideally 205mm.'
                    messages.append({'role': 'user', 'content': repair})
                except Exception as exc:
                    failure = safe_api_error(provider, exc, model=model)
                    errors.append(f'{label}: {failure}')
                    LOGGER.warning('%s', errors[-1])
                    if not failure.retryable or getattr(exc, 'status_code', None) == 429:
                        break
                if attempt < 2:
                    time.sleep(min(2 ** attempt + random.random(), 10))
        finally:
            api.close()
    raise ActivityGenerationError('; '.join(dict.fromkeys(errors))) from None


def validate_plan(raw: dict, count: int) -> dict:
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
    for key in ('title', 'activity_concept', 'layout_brief'):
        if len({p[key].strip().casefold() for p in plan['pages']}) != count:
            raise ValueError(f'Each page needs a different {key}; do not repeat a worksheet pattern')
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


def validate_design(raw: dict, font: int, *, cover: bool = False) -> dict:
    """Require complete art-backed HTML and preflight it at actual print dimensions."""
    if not isinstance(raw, dict):
        raise ValueError('Design must be an object')
    design = deepcopy(raw)
    design['html'] = _text(design.get('html'), 'html', 18000)
    if not cover:
        answers = design.get('answers')
        if isinstance(answers, list) and 1 <= len(answers) <= 30 and all(isinstance(a, str) and a.strip() for a in answers):
            answers = '; '.join(answers)
        design['answers'] = _text(answers, 'answers', 4000)
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
    check_page(design, font, cover=cover)
    return design


def compact_answers(page: dict, number: int) -> dict:
    """Shorten only an oversized key; never redesign the already validated worksheet."""
    if len(page['answers']) <= 300:
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


def layout_contract(font: int) -> str:
    """Describe the print boundary without prescribing a reusable composition."""
    return f'''Return JSON with html (one complete HTML fragment, <=18000 chars), images
(1-4 objects with id and prompt <=650 chars), and answers (one concise string <=300 chars,
number EVERY answer to match the student tasks; include a sample/criterion for open responses).
Canvas: A4, 186mm wide, content at most 265mm high. No html/head/body/style tags.
Choose YOUR OWN layout, palette, typographic hierarchy, borders, panels and response spaces.
Allowed tags: {sorted(TAGS)}. Only inline style attributes; no classes or external files.
Allowed CSS properties: {sorted(PROPERTIES)}. Use valid simple CSS, positive mm dimensions,
percent widths, colors, numeric line-height >=1.15. Font-size preferably in pt, 11-40pt; px
is converted at 0.75pt per px and sizes are normalized to 11-40pt before print checks. Student text
should usually be {font}pt or larger. Use tables or flex for columns; no CSS grid, positioning,
floats, transforms, overflow hiding, scripts, SVG, negative spacing, URLs or font imports.
Images: <img data-asset="asset_id" style="width:80mm;height:55mm"/>.
Declare and use every image. All images need BOTH explicit width and height, with height in mm.
Images are fitted without cropping. Illustration prompts must describe original meaningful
scenes or objects without text, labels, numbers, page borders or worksheet layouts.
Python renders all written content. Draw exact quantities, diagrams, number lines, answer
boxes and symbols using HTML/text; never depend on image-model accuracy for a numeric answer.
Do not put solutions in student HTML. Include clear directions, numbered tasks, and sufficient
writing/cutting/drawing space appropriate to the activity. Never refer to missing materials.
Use normal document flow and leave breathing room; aim for 245mm total content height.
Include padding, margins, borders and table spacing in the 186mm width budget.
Prefer auto-width table cells; percentage cell widths plus padding may overflow.
Use white-space:normal, pre-wrap or pre-line if needed. Long text and answer lines must wrap.
Python can reflow oversized table columns and reduce excessive paragraph/cell spacing,
but it will not shrink text, remove questions, or reduce explicit response-area heights.
Do not fill the sheet with tiny text.
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
activity_concept <=650, layout_brief <=650. No teacher guide.'''
    plan = ask_json(plan_prompt, lambda raw: validate_plan(raw, count), 'Creative plan', 6000)
    context = json.dumps({k: plan[k] for k in ('title', 'art_direction', 'character_description')})
    def design_unit(number):
        """Author one independent page while preserving caller-owned page numbering."""
        if number == 0:
            return ask_json(f'Create an illustrated cover for {grade_band}. {context}\n{plan["cover_brief"]}\n'
                     + layout_contract(font) + '\nThis is the cover: omit student tasks and answers. Include the pack title and grade. '
                     'Python places the REAL store logo in a separate 41mm header above your content. '
                     'Do not draw a logo or repeat the store name. Override the full-page height: '
                     'YOUR cover fragment must be at most 215mm high; aim for 205mm including all spacing.',
                     lambda raw: validate_design(raw, font, cover=True), 'Cover design')
        brief = plan['pages'][number - 1]
        prompt = (f'Author student activity {number} for {grade_band}. Theme: {theme}. '
                  f'User context: {source_context or theme}. Skills: {config["skill_notes"]}.\n'
                  f'Art direction: {context}\nThis page brief: {json.dumps(brief)}\n'
                  f'Other planned layouts (make this page distinct): {json.dumps([p["layout_brief"] for p in plan["pages"]])}\n'
                  + layout_contract(font) + f'\nPrint activity number {number} and its title prominently.')
        page = ask_json(prompt, lambda raw: validate_design(raw, font), f'Activity design {number}')
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
                resource_type='activity_pack', design_engine='creative_html_v1', cover=cover, pages=pages)
    preflight_pack(pack, config)
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
    paths = generate_images(image_pack, styles, folder)
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
