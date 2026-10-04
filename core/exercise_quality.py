"""Check printable exercise contracts and proofread text without reviewing image pixels."""
from __future__ import annotations

import ast
from fractions import Fraction
from html.parser import HTMLParser
from html import unescape
import json
import re
import unicodedata

from core.task_visuals import page_visuals, answer_text


class StudentText(HTMLParser):
    """Extract visible text and identify every graphic's role for text proofreading."""

    def __init__(self, page: dict):
        """Keep the known image brief map without loading images or files."""
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.images = {a['id']: a['prompt'] for a in page.get('images', [])}
        self.visuals = {v['id']: v for v in page.get('visuals', [])}

    def handle_data(self, data: str) -> None:
        """Collect ordinary worksheet text."""
        if data.strip():
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Mark graphics as graphics rather than pretending to inspect their pixels."""
        attrs = dict(attrs)
        if tag == 'img':
            if 'data-asset' in attrs:
                self.parts.append('[AI artwork brief: '+self.images.get(attrs['data-asset'], 'UNKNOWN')+']')
            if 'data-visual' in attrs:
                self.parts.append('[Exact Python visual: '+json.dumps(self.visuals.get(attrs['data-visual']))+']')


def student_text(page: dict) -> str:
    """Return printable text and semantic graphic references with HTML entities decoded."""
    parser = StudentText(page)
    parser.feed(page['html'])
    return '\n'.join(parser.parts)


def activity_title(value: str) -> str:
    """Separate a model-added page label from the actual activity title."""
    return re.sub(r'^\s*(?:page|activity)\s+#?\d+\s*[:.\-–—]\s*', '', value,
                  flags=re.I).strip()


def title_words(value: str) -> str:
    """Compare visible title words regardless of typography or punctuation."""
    value = unicodedata.normalize('NFKC', unescape(value)).casefold()
    value = value.replace('&', ' and ').replace('’', "'").replace("'", '')
    return ' '.join(re.sub(r'[\W_]+', ' ', value).split())


def calculate(expression: str) -> Fraction:
    """Evaluate bounded elementary arithmetic without eval or executable model code."""
    if not isinstance(expression, str) or len(expression) > 80:
        raise ValueError('Calculation expression must be text of at most 80 characters')
    expression = expression.strip().replace('×','*').replace('÷','/').replace('−','-')
    expression = re.sub(r'(?<=\d)\s*[xX]\s*(?=\d)', '*', expression)
    try:
        root = ast.parse(expression, mode='eval')
    except SyntaxError:
        raise ValueError('Invalid arithmetic expression') from None
    if len(list(ast.walk(root))) > 35:
        raise ValueError('Arithmetic expression is too complex')
    def visit(node):
        """Resolve bounded numeric literals exactly and four arithmetic operations."""
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            # Read the original decimal spelling, avoiding binary float rounding.
            literal = ast.get_source_segment(expression, node) or ''
            if re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)', literal):
                value = Fraction(literal)
                if abs(value) <= 10000:
                    return value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                result = a+b
            elif isinstance(node.op, ast.Sub):
                result = a-b
            elif isinstance(node.op, ast.Mult):
                result = a*b
            else:
                if not b:
                    raise ValueError('Division by zero')
                result = a/b
            if abs(result) > 1000000:
                raise ValueError('Arithmetic result is too large')
            return result
        raise ValueError('Only integer/decimal literals, parentheses and + - * / are allowed; '
                         'no variables, equations, units, percent signs or powers')
    return visit(root.body)


def numeric_display_text(value: str) -> str:
    """Normalize only explicit numeric grouping/currency, leaving surrounding wording intact."""
    value = re.sub(r'(?<![\w.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w.,])',
                   lambda match:match[0].replace(',',''),value)
    return re.sub(r'[$£€](?=\s*(?:\d|\.\d))','',value)


def rounding_precision(prompt: str) -> int | None:
    """Read one unambiguous explicit printed decimal precision; never assume currency rounding."""
    text = prompt.casefold()
    precisions = set()
    units = {'cent':2,'cents':2,'hundredth':2,'hundredths':2,'tenth':1,'tenths':1,
             'thousandth':3,'thousandths':3,'whole number':0,'whole dollar':0,'dollar':0}
    for match in re.finditer(r'\bnearest\s+(cent[s]?|hundredths?|tenths?|thousandths?|whole number|whole dollar|dollar)\b',text):
        precisions.add(units[match[1]])
    words = {'zero':0,'one':1,'two':2,'three':3,'four':4}
    for match in re.finditer(r'\b(?:round(?:ed)?(?:\s+(?:the\s+)?(?:answer|result))?\s+to|to)\s+(\d+|zero|one|two|three|four)\s+decimal places?\b',text):
        places = words[match[1]] if match[1] in words else int(match[1])
        if places>4:
            raise ValueError('Use at most four decimal places in printed rounding instructions')
        precisions.add(places)
    if len(precisions)>1:
        raise ValueError('Printed rounding instructions conflict; specify one precision')
    if not precisions:
        return None
    return next(iter(precisions))


def expected_calculation(expression: str, prompt: str = '') -> Fraction:
    """Apply only an explicit printed rounding instruction, using exact half-up arithmetic."""
    actual = calculate(expression)
    places = rounding_precision(prompt)
    if places is None:
        return actual
    scale = 10**places
    scaled = abs(actual)*scale
    whole, remainder = divmod(scaled.numerator,scaled.denominator)
    if remainder*2 >= scaled.denominator:
        whole += 1
    return Fraction((-whole if actual<0 else whole),scale)


def normalize_calculation(expression: str) -> str:
    """Canonicalize explicit numeric notation without guessing equations or running model code."""
    if not isinstance(expression,str) or len(expression)>80:
        raise ValueError('Calculation expression must be text of at most 80 characters')
    value = expression.strip().replace('−','-').replace('–','-')
    value = value.replace('×','*').replace('⋅','*').replace('·','*').replace('÷','/')
    value = re.sub(r'(?<=[\d)])\s*[xX]\s*(?=[\d(])','*',value)
    value = numeric_display_text(value)
    # Percent suffix is a numeric literal, not Python's modulo operator. Reject
    # ambiguous forms such as 10%3 and wording such as "15% of the class".
    value = re.sub(r'(?<![\w.])(\d+(?:\.\d+)?|\.\d+)\s*%(?!\s*[\d.\w])',r'(\1/100)',value)
    value = value.strip()
    calculate(value)  # The existing restricted AST evaluator remains the safety boundary.
    return value


def validate_exercises(page: dict, config: dict, expected_title: str | None = None) -> None:
    """Reject known impossible tasks and verify declared math before image spending."""
    visuals = page_visuals(page)
    prose = student_text(page)
    normalized = ' '.join(prose.split()).casefold()
    if expected_title:
        expected_words = title_words(activity_title(expected_title))
        # Artwork briefs are not printed headings and must not satisfy this check.
        visible_parser = HTMLParser()
        visible_parts = []
        visible_parser.handle_data = visible_parts.append
        visible_parser.feed(page['html'])
        visible_words = title_words(' '.join(visible_parts))
        if not expected_words or f' {expected_words} ' not in f' {visible_words} ':
            raise ValueError(f'Print the exact planned activity title: {activity_title(expected_title)}. '
                             'Put it visibly in h1 or h2; preserve the exercise and artwork.')
    kinds = {v['kind'] for v in page.get('visuals', [])}
    if re.search(r'\bmaze\b', normalized) and not re.search(r'(draw|design|create).{0,30}(your|an?).{0,15}maze', normalized) and 'maze' not in kinds:
        raise ValueError('A maze task requires an exact visuals kind=maze component, not an AI picture of a path')
    if re.search(r'(find|spot|circle).{0,60}\bdifferences?\b', normalized) and 'differences' not in kinds:
        raise ValueError('Spot-the-difference tasks require an exact visuals kind=differences component with both rows')
    checks = page.get('calculations', [])
    if not isinstance(checks, list) or len(checks) > 16:
        raise ValueError('calculations must be a list of at most 16 arithmetic checks')
    # Independently derive printed arithmetic facts even if the author omits a check.
    facts = []
    for match in re.finditer(r'(?<![\w.])(\d+(?:\.\d+)?|\.\d+)\s*([+−×÷*/-])\s*(\d+(?:\.\d+)?|\.\d+)(?!\w|\.\d)', numeric_display_text(prose)):
        expression = ''.join(match.groups())
        value = calculate(expression)
        facts.append({'expression': expression, 'result': str(value)})
    page['computed_math'] = facts
    numbers = set()
    for index, item in enumerate(checks, 1):
        if isinstance(item, dict):
            reference = item.get('question')
            # Gemini often serializes a printed numeric task label as a JSON number.
            # Preserve that explicit identity; never infer one from list position.
            if type(reference) is int and 1 <= reference <= 999:
                item['question'] = str(reference)
            elif isinstance(reference, str):
                item['question'] = reference.strip()
        if not isinstance(item, dict) or not isinstance(item.get('question'), str) or not 1 <= len(item['question']) <= 20:
            raise ValueError(f'Each calculation needs a short question reference; calculations item {index} '
                             'requires question as nonempty text matching its printed task, e.g. "1" or "2A"')
        if item['question'] in numbers:
            raise ValueError('Calculation question references must be unique')
        numbers.add(item['question'])
        try:
            canonical = page.get('exercise',{}).get('questions',[]) if page.get('exercise_binding') else []
            task = next((q.get('prompt','') for q in canonical if str(q.get('id'))==item['question']), '')
            raw_result = calculate(item.get('expression'))
            actual = expected_calculation(item.get('expression'),task)
        except ValueError as exc:
            raise ValueError(f'Question {item["question"]}: calculation expression '
                             f'{str(item.get("expression"))[:80]!r}: {exc}') from None
        try:
            provided = Fraction(str(item.get('answer')))
        except (ValueError, ZeroDivisionError):
            raise ValueError('Calculation answer must be a number or fraction string') from None
        if provided != actual:
            raise ValueError(f'Question {item["question"]}: {item["expression"]} equals {actual}, not {item["answer"]}')
        if raw_result < 0 or raw_result > config.get('max_result', 10000):
            raise ValueError(f'Question {item["question"]}: Arithmetic result is outside this grade band; '
                             f'allowed result 0 to {config.get("max_result",10000)}, got {raw_result}. '
                             'Simplify this question and its calculation together; preserve other tasks')
        if config.get('max_result', 10000) <= 100 and raw_result.denominator != 1:
            raise ValueError('Use whole-number results for younger grades')
    if visuals and not page.get('exercise_binding') and len(answer_text(page)) > 650:
        raise ValueError('Keep the combined exact-puzzle and written answers within 650 characters')


def validate_audit(raw: dict, expected: set[int]) -> dict:
    """Require a verdict for every page; missing pages never count as approval."""
    rows = raw.get('pages') if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError('Proofreading must return every requested page exactly once')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get('page_number')) is not int:
            raise ValueError('Proofreading page_number must be an integer')
        n, issues = row['page_number'], row.get('issues')
        if n not in expected or n in result:
            raise ValueError('Unexpected or duplicate proofreading page')
        if not isinstance(issues, list) or len(issues) > 4 or any(not isinstance(v,str) or not 1 <= len(v) <= 260 for v in issues):
            raise ValueError('Return at most four concrete short content issues per page')
        result[n] = issues
    return result


def proofread_pack(pack: dict, ask, repair) -> None:
    """Audit text/answers in one batch; repair affected pages once and recheck them all."""
    expected = set(range(1, len(pack['pages'])+1))
    for attempt in range(2):
        payload = [{'page_number': i, 'title': page['title'], 'student_content': student_text(page),
                    'answer_key': answer_text(page), 'verified_calculations': page.get('calculations', []),
                    'independent_printed_math': page.get('computed_math', []),
                    'planned_intent': page.get('planned_intent'), 'shared_exercise': page.get('exercise'),
                    'original_answer_conditions': page.get('answer_key_original')}
                   for i, page in enumerate(pack['pages'], 1)]
        prompt = (
            'Proofread the educational CONTENT of this static classroom pack. This is NOT image review. '
            'Do not request images, judge image quality or speculate about generated pixels. '
            'Return JSON {"pages":[{"page_number":1,"issues":[]}]} for EVERY page. '
            f'Grade: {pack["grade_band"]}. Identify only concrete mistakes making a task incorrect, '
            'ambiguous, unsolvable or mismatched to its answer key. Independently solve printed math; '
            'match question numbers, titles and EVERY answer; check comprehension against supplied passage, '
            'if original_answer_conditions are supplied, verify concise answers preserve their essential '
            'solutions and success conditions; flag any omitted required condition or changed value. '
            'compare the planned activity with the shared exercise and actually printed task. Flag substituted '
            'mechanisms, e.g. sorting beneath seesaw directions or a maze beneath a pattern instruction. '
            'exhaustive/nonoverlapping sorting rules and sufficient materials. Flag genuinely near-identical '
            'student tasks repeated with changed titles, not repeated broad mechanic labels. Drawing, '
            'coloring or craft pages may share a label while developing distinct concepts and responses; '
            'do not flag that alone or shared themes/palettes. Flag a required visual '
            'replaced with text labels, empty panels, CSS-only drawings, or an illustrative scene. '
            'Exact Python visuals are guaranteed from their specs: maze route/tokens, differences, sort, '
            'patterns, matching, size comparison and counts have computed answers. '
            'answers are supplied by Python; their numbered directions are printed inside the graphic. '
            'Locally generated blank templates (images.local_template) are intentionally empty student '
            'work surfaces, not missing illustrations. A drawing or design task may use them. '
            'Check that sentence completion prints its starter. Check that captions do not call '
            'plain circles pottery or stars gourds. A cultural theme needs substantive, accurate '
            'learning context, not only a theme label on unrelated generic puzzles; avoid treating '
            'diverse communities as one culture or invented traditional practices. '
            'Other images are decorative/illustrative only: a task must not depend on their exact count, '
            'spelling, path, tiny detail or a specific hidden object. Open drawing/writing can use general art. '
            'Flag questions whose answer is accidentally printed in the question, unless a worked example. '
            'Do not flag stylistic preferences, benign answer variations, absent solutions on student pages '
            'or insist that artwork contains text supplied separately by HTML. List at most four specific '
            'issues per page, <=260 chars each; use [] when no concrete issue is found. Content follows:\n'
            + json.dumps(payload))
        issues = ask(prompt, lambda raw: validate_audit(raw, expected), 'Exercise proofreading', 4000)
        failed = {n: reasons for n, reasons in issues.items() if reasons}
        if not failed:
            pack['content_checks'] = {'status': 'passed', 'pages': len(expected), 'repair_rounds': attempt,
                                      'method': 'local_puzzle_math_checks_and_text_proofreading'}
            return
        if attempt:
            details = '; '.join(f'Activity {n}: '+ '; '.join(reasons) for n,reasons in failed.items())
            raise ValueError('Exercise content still needs correction: '+details)
        for n, reasons in failed.items():
            pack['pages'][n-1] = repair(n, pack['pages'][n-1], reasons)
