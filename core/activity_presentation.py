"""Turn validated puzzle data into useful, truthful printable student pages."""
from copy import deepcopy
import math
import re

from core.task_visuals import build_visual


def activity_quality_guidance(grade_band: str) -> str:
    """Explain useful practice and task-specific artwork without prescribing a pack menu."""
    return f'''Product quality for {grade_band}: every page must offer a substantial student action.
Counting sheets need THREE visibly separate rows with different quantities, not one tiny row.
Matching needs 4 pairs; sorting needs 6-8 large cards. A single drawing, craft or maze may fill
one page when its actual work surface is large. Do not add unrelated questions to fill space.
Titles must describe the real task AND visible materials: colored ghosts are not costumes;
comparing two rows is not a hidden-object hunt; generic shapes are not candy corn. For exact
pages Python derives the final title from the actual puzzle. Use thematic symbols supported by
the tool, rather than promising unsupported objects. Never substitute generic shapes for
an explicitly requested object; use an authored open activity when that object is essential.
Artwork must be task-specific: a face-drawing task needs a large FACELESS outline; a coloring
activity needs uncolored line art; a cut-and-build task needs large separated usable pieces.
Avoid repeated smiling mascot pictures, generic scenery and tiny decorative header art.
For Pre-K/K use directions of roughly 5-12 words per action, with adult support when needed.
Do not reference above/below/left/right unless the final layout guarantees that location.
Each page must have a different useful learning experience. Include creative making, drawing,
tracing or designing where appropriate, with generous usable workspace and bold clean art.
Use a coordinated accent palette and strong visual hierarchy across the whole pack.
Keep a strong substantive connection to the context: do not attach a heritage-month label to
a generic sequence of shapes, Halloween symbols or harvest mascots. For cultural themes,
include specific, accurate contemporary communities and experiences; avoid generalized
costumes, pan-Indigenous motifs or attributing one practice to every Native nation.
Prefer at least three quarters authored context-specific activities unless the user explicitly
requests numerical puzzles. Use plain, age-appropriate language and brief factual context.
Sentence-completion tasks MUST print their actual sentence starters.
Blank templates must explicitly say blank in directions; Python supplies their uncolored
work surface. Do not request already patterned, colored or completed worksheet artwork.
'''


def prepare_activity_presentation(page: dict, brief: dict, config: dict) -> tuple[dict, dict]:
    """Compose exact pages from valid puzzle data; retain authored content and all extra tasks."""
    page, brief = deepcopy(page), deepcopy(brief)
    from core.print_tags import normalize_print_markup
    page['html'] = normalize_print_markup(page.get('html', ''))
    validate_source_markup(page['html'])
    if page.get('_canonical_presentation'):
        if page.get('title'):
            brief['title'] = page['title']
        return page, brief
    exercise = page.get('exercise')
    if not isinstance(exercise, dict):
        return page, brief
    if exercise.get('render_mode') != 'exact':
        # Canonical question blocks include their answer workspace. Use a neutral
        # reference so model-authored directions cannot point to a decorative image.
        for question in exercise.get('questions', []):
            if isinstance(question, dict) and isinstance(question.get('prompt'), str):
                question['prompt'] = re.sub(r'\b(?:(?:big|large|empty)\s+)?box\s+(?:above|below)\b',
                                           'answer box', question['prompt'], flags=re.I)
        page = prepare_authored_flow(page, config)
        if isinstance(page.get('images'), list) and page['images']:
            page['_canonical_presentation'] = True
        return page, brief
    visual = exercise.get('visual')
    if not isinstance(visual, dict):
        return page, brief
    visual = deepcopy(visual)
    for key, value in brief.get('mechanic_constraints', {}).items():
        if key not in visual:
            visual[key] = value
    # Validate before adding practice: invalid puzzles still follow the usual repair path.
    try:
        build_visual(visual)
    except (ValueError, TypeError, KeyError):
        return page, brief
    if visual['kind'] == 'count' and len(visual['rows']) < 3:
        row = visual['rows'][0]
        used = {len(r) for r in visual['rows']}
        maximum = min(10, config.get('max_operand', 10))
        for n in sorted(range(1, maximum + 1), key=lambda n: (abs(n - len(row)), n)):
            if n not in used:
                visual['rows'].append([deepcopy(row[i % len(row)]) for i in range(n)])
                used.add(n)
            if len(visual['rows']) == 3:
                break
    svg, _ = build_visual(visual)
    exercise['visual'] = visual
    shapes = set()
    def collect(value):
        """Collect actual symbols, excluding incidental prose in the brief."""
        if isinstance(value, dict):
            if 'shape' in value:
                shapes.add(value['shape'].lower())
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(visual)
    subject = next(iter(shapes)).replace('_', ' ').title() if len(shapes) == 1 else 'Picture'
    plural = 'Leaves' if subject == 'Leaf' else subject + 's'
    titles = {'count': f'Count the {plural}', 'pattern': f'{subject} Pattern Challenge',
              'matching': f'Match the {plural}' + (' and Shadows' if visual.get('mode') == 'shadow' else ''),
              'sort': f'{subject} Sort: {visual.get("attribute", "shape").title()}',
              'differences': f'{subject} Changes: Compare the Rows',
              'balance': f'{subject} Sizes: Find the Larger One', 'maze': 'Star Trail Maze' if visual.get('tokens') else 'Follow the Maze Path'}
    title = titles[visual['kind']]
    brief['title'] = title
    page['title'] = title
    # A repeated planned title is redundant; retain all other contextual captions.
    exercise['captions'] = [c for c in exercise.get('captions', [])
                            if c.get('text', '').strip().casefold() not in
                            {title.casefold(), str(page.get('planned_title', '')).casefold()}]
    font = config.get('student_font_pt', 14)
    accent = config.get('accent', '#007F82')
    wash = config.get('wash', '#E3F5EF')
    height = float(re.search(r'height="([0-9.]+)"', svg)[1])
    width = 175
    printed_height = math.ceil(width * height / 720)
    parts = [f'<h1 data-content="title" style="font-size:{font+5}pt;color:{accent};'
             f'background-color:{wash};padding:3mm;margin:0 0 3mm;border-radius:4mm"></h1>',
             f'<p data-content="name" style="font-size:{font}pt;margin:0 0 3mm"></p>']
    for caption in exercise['captions']:
        parts.append(f'<p data-content="caption_{caption["id"]}" '
                     f'style="font-size:{font}pt;margin:0 0 2mm"></p>')
    for asset in page.get('images', []):
        art_height = 30 if printed_height > 150 else 45
        parts.append(f'<div style="text-align:center;margin:0 0 2mm"><img data-asset="{asset["id"]}" '
                     f'style="width:175mm;height:{art_height}mm"/></div>')
    parts.append(f'<div style="text-align:center;border:0.5mm solid {accent};'
                 f'padding:2mm;border-radius:4mm;margin:0 0 3mm">'
                 f'<img data-visual="{visual["id"]}" style="width:{width}mm;height:{printed_height}mm"/></div>')
    for question in exercise.get('questions', []):
        parts.append(f'<div data-content="question_{question["id"]}" '
                     f'style="font-size:{font}pt;margin:0 0 3mm"></div>')
    page['html'] = ''.join(parts)
    page.setdefault('images', [])
    page['_canonical_presentation'] = True
    return page, brief


def prepare_authored_flow(page: dict, config: dict) -> dict:
    """Lay out canonical reading, art and tasks in flow without fixed-height text columns."""
    exercise = page['exercise']
    images = page.get('images')
    if not isinstance(images, list) or not images:
        return page  # Let the normal manifest validator explain missing artwork.
    from core.blank_templates import template_kind
    kind = template_kind(exercise)
    if kind and len(images) == 1:
        images[0]['local_template'] = kind
        images[0]['prompt'] = f'Blank uncolored {kind.replace("_", " ")} student work surface; no completed designs.'
    for question in exercise.get('questions', []):
        prompt, answer = question.get('prompt', ''), question.get('answer', '')
        if not isinstance(prompt, str) or not isinstance(answer, str):
            continue
        if re.search(r'complete\s+(?:the\s+)?(?:first|second|third)?\s*sentence', prompt, re.I):
            starter = re.search(r'(?:starting with|beginning with|starts with)\s*[\'"]([^\'"]+)', answer, re.I)
            if starter:
                if starter[1].rstrip('. ') not in prompt:
                    question['prompt'] = prompt.rstrip(' :') + ' Start with: ' + starter[1]
            else:
                question['prompt'] = re.sub(r'complete\s+(?:the\s+)?(?:first|second|third)?\s*sentence',
                                             'Write a sentence', prompt, flags=re.I)
    font = config.get('student_font_pt', 14)
    accent, wash = config.get('accent', '#007F82'), config.get('wash', '#E3F5EF')
    parts = [f'<h1 data-content="title" style="font-size:{font+5}pt;color:{accent};'
             f'background-color:{wash};padding:3mm;margin:0 0 3mm"></h1>',
             f'<p data-content="name" style="font-size:{font}pt;margin:0 0 2mm"></p>',
             f'<p data-content="directions" style="font-size:{font}pt;margin:0 0 3mm"></p>']
    for caption in exercise.get('captions', []):
        parts.append(f'<p data-content="caption_{caption["id"]}" '
                     f'style="font-size:{font}pt;color:{accent};margin:0 0 2mm"></p>')
    if exercise.get('passage'):
        parts.append(f'<div data-content="passage" style="font-size:{font}pt;'
                     f'background-color:{wash};padding:3mm;margin:0 0 3mm"></div>')
    # Budget artwork against retained text and response space, not tiny sidebar columns.
    chars = len(str(exercise.get('directions', ''))) + len(str(exercise.get('passage', '')))
    chars += sum(len(str(c.get('text', ''))) for c in exercise.get('captions', []))
    chars += sum(len(str(q.get('prompt', ''))) for q in exercise.get('questions', []))
    response = sum(q.get('space_mm', 0) for q in exercise.get('questions', [])
                   if isinstance(q.get('space_mm', 0), (int, float)))
    text_height = math.ceil(chars / max(45, 1000 / font)) * font * 0.46
    minimum_art_height = max(35, math.ceil(config.get('visual_area_mm2', 10000) / 175))
    artwork_height = max(minimum_art_height, min(100, 225 - 45 - text_height - response))
    if 2 <= len(images) <= 4:
        from core.illustration_gallery import illustration_gallery, gallery_minimum_height
        height = max(artwork_height, gallery_minimum_height(len(images),config.get('visual_area_mm2',10000)))
        parts.append(illustration_gallery([asset['id'] for asset in images],height))
    else:
        for asset in images:
            parts.append(f'<div style="text-align:center;margin:0 0 3mm">'
                         f'<img data-asset="{asset["id"]}" style="width:175mm;'
                         f'height:{artwork_height / len(images):g}mm"/></div>')
    for question in exercise.get('questions', []):
        parts.append(f'<div data-content="question_{question["id"]}" '
                     f'style="font-size:{font}pt;margin:0 0 3mm"></div>')
    page['html'] = ''.join(parts)
    return page


def validate_source_markup(markup: str) -> None:
    """Never let canonical recomposition turn active or external model markup into success."""
    from html.parser import HTMLParser
    from core.creative_layout import TAGS, clean_style
    from core.print_tags import TAG_ALIASES, PASSIVE_ATTRIBUTES, normalize_print_markup
    class Guard(HTMLParser):
        """Check allowed elements and attributes before replacing the source composition."""
        def handle_starttag(self, tag, attrs):
            """Reject scripts, remote resources and active attributes in the raw response."""
            tag = TAG_ALIASES.get(tag,tag)
            if tag not in TAGS:
                raise ValueError(f'Unsupported HTML tag: {tag}')
            functional = [(key,value) for key,value in attrs if key not in PASSIVE_ATTRIBUTES]
            if len({key for key,_ in functional}) != len(functional):
                raise ValueError('Duplicate layout attributes')
            for key, value in attrs:
                if key in PASSIVE_ATTRIBUTES:
                    continue
                if key not in {'style','data-asset','data-visual','data-content','colspan','rowspan'}:
                    raise ValueError(f'Unsupported print attribute {key!r} on <{tag}>; use only '
                                     'style, data-content, data-asset, data-visual, colspan and rowspan. '
                                     'Put presentation values in inline style and remove nonprint attributes')
                if key == 'style':
                    clean_style(value or '', 11)
        def handle_startendtag(self, tag, attrs):
            """Apply the same guard to self-closing image tags."""
            self.handle_starttag(tag, attrs)
    guard = Guard()
    guard.feed(normalize_print_markup(markup))
    guard.close()
