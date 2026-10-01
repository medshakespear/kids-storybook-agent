"""Bind creative layouts to one exercise specification, with no parallel answer draft."""
from __future__ import annotations

import html
import re
from copy import deepcopy
from html.parser import HTMLParser

from core.task_visuals import normalize_visual_metadata, page_visuals

EXACT_MECHANICS = {'maze', 'sort', 'differences', 'pattern', 'matching', 'balance', 'count'}


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
        self.assets, self.visuals = [], []
        self.visual_styles = {}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Replace empty content placeholders and preserve design-only wrappers."""
        if self.slot:
            raise ValueError('Content slots must be empty; exercise specification supplies their text')
        data = dict(attrs)
        if len(data) != len(attrs):
            raise ValueError('Duplicate layout attributes')
        block = data.pop('data-content', None)
        if block is not None:
            if tag not in {'h1','h2','h3','h4','p','div','span','section','td'}:
                raise ValueError('Use a text container for data-content slots')
            if block not in self.blocks or block in self.used:
                raise ValueError(f'Unknown or repeated exercise content slot: {block}')
            self.used.add(block)
            self.slot = block
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
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError('Exercise layout tags must be balanced')
        _,block = self.stack.pop()
        if block: self.slot = None
        self.parts.append(f'</{tag}>')

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Support ordinary self-closing artwork, breaks and empty content slots."""
        self.handle_starttag(tag,attrs)
        if tag not in {'img','br'}: self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        """Reject text outside canonical slots, including leaked answers and stray directions."""
        if data.strip():
            raise ValueError('Put ALL printed wording in exercise fields and empty data-content slots; no independent layout text')

    def handle_comment(self, data: str) -> None:
        """Reject hidden duplicate instruction drafts in layout comments."""
        raise ValueError('Do not put content or comments in the exercise layout')


def validate_brief(page: dict) -> None:
    """Require a concrete planned mechanism without restricting authored creative tasks."""
    if page.get('render_mode') not in {'exact','authored'}:
        raise ValueError('Each page needs render_mode exact or authored')
    mechanic = bounded_text(page.get('mechanic'), 'mechanic', 50)
    if page['render_mode'] == 'exact' and mechanic not in EXACT_MECHANICS:
        raise ValueError(f'Exact mechanic must be one of {sorted(EXACT_MECHANICS)}; use authored for other creative exercises')


def compile_exercise(page: dict, config: dict, title: str, brief: dict | None = None) -> None:
    """Build printed tasks, calculation checks and answer key from the same data."""
    if any(page.get(k) for k in ('answers','visuals','calculations')):
        raise ValueError('Use only the shared exercise specification, not independent answers/visuals/calculations drafts')
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
        if exercise.get('directions') or exercise.get('passage'):
            raise ValueError('Exact visual prints its own verified directions; omit parallel directions/passage to avoid task mismatches')
        visual = exercise.get('visual')
        if not isinstance(visual,dict) or visual.get('kind') != exercise['mechanic']:
            raise ValueError('Exercise visual kind must match its planned exact mechanic')
        page['visuals'] = [visual]
        normalize_visual_metadata(page)
        exercise['visual'] = page['visuals'][0]
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
            raise ValueError('Exercise question IDs must be distinct printed labels, e.g. 1 or 2A; do not duplicate visual question numbers')
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
            if actual != supplied: raise ValueError(f'Question {qid}: declared math answer is incorrect; correct the shared specification')
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
    parser = BoundLayout(blocks)
    parser.feed(layout); parser.close()
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
        raise ValueError('Render every purposeful exercise illustration exactly once')
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
Python checks actual final answer-sheet fit, not an arbitrary per-page aggregate length. exercise: {render_mode, mechanic, goal, directions?, passage?, visual?, questions:[]}.
Preserve render_mode and mechanic from the planned brief. Do not substitute sorting for balancing,
matching for mazes, or a maze for completing a pattern. If the chosen task cannot be rendered, repair
THIS task rather than replacing it with another mechanism.
- exact: visual contains ONE exact component with kind=mechanic. Omit directions and passage;
  Python prints the computed task directions inside that graphic. Include the graphic once via img
  data-visual. questions may contain related optional actions with DIFFERENT IDs; no duplicated
  directions or answers about the exact visual. Do not return a parallel top-level visuals list.
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
Passage, if provided: <div data-content="passage"></div>. Each question needs exactly one slot:
<div data-content="question_1"></div>. Python fills prompt, number and response space together.
Use ordinary div/section/table/panels, inline styles and images to invent original compositions.
Do not put independent text, numbers, labels, comments or task instructions in html. Do not fill
slots yourself. Never return a separate answers/calculations draft: Python derives both from exercise.
Artwork supports task context or open-ended creation. Closed answers must not require identifying
exact pixels, hidden objects, missing costume pieces, specific faces or counting AI-generated objects.
For lower grades use a large useful illustration, expressive craft/coloring material or a large exact
visual; avoid mascot thumbnails. Use few short adult-read directions and ample physical response space.
'''
