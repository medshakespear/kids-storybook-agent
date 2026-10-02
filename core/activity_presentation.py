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
'''


def prepare_activity_presentation(page: dict, brief: dict, config: dict) -> tuple[dict, dict]:
    """Compose exact pages from valid puzzle data; retain authored content and all extra tasks."""
    page, brief = deepcopy(page), deepcopy(brief)
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
        return page, brief
    visual = exercise.get('visual')
    if not isinstance(visual, dict) or page.get('images') not in ([], None):
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
    parts.append(f'<div style="text-align:center;border:0.5mm solid {accent};'
                 f'padding:2mm;border-radius:4mm;margin:0 0 3mm">'
                 f'<img data-visual="{visual["id"]}" style="width:{width}mm;height:{printed_height}mm"/></div>')
    for question in exercise.get('questions', []):
        parts.append(f'<div data-content="question_{question["id"]}" '
                     f'style="font-size:{font}pt;margin:0 0 3mm"></div>')
    page['html'] = ''.join(parts)
    page['images'] = []
    return page, brief
