"""Derive declared calculation results without asking a language model to perform arithmetic."""
from copy import deepcopy
from fractions import Fraction
import re

from core.exercise_quality import expected_calculation,normalize_calculation,rounding_precision


NUMBER = re.compile(r'(?<![\w.])-?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(?:/\d+)?(?![\w.])')


def format_result(value: Fraction, prompt: str) -> str:
    """Print explicitly rounded results as decimals without floating point loss."""
    places = rounding_precision(prompt)
    if places is None or places == 0:
        return str(value)
    scaled = value * 10 ** places
    if scaled.denominator != 1:
        raise ValueError('Rounded result does not match its declared precision')
    sign = '-' if scaled < 0 else ''
    digits = str(abs(scaled.numerator)).zfill(places + 1)
    return sign + digits[:-places] + '.' + digits[-places:]


def repair_declared_result(page: dict, question_id: str) -> dict | None:
    """Correct one unambiguous numeric key result; keep the authored operation and question."""
    exercise = page.get('exercise') if isinstance(page,dict) else None
    questions = exercise.get('questions') if isinstance(exercise,dict) else None
    matches = [q for q in questions if isinstance(q,dict) and str(q.get('id'))==question_id] if isinstance(questions,list) else []
    if len(matches)!=1:
        return None
    question = matches[0]
    calculation = question.get('calculation')
    answer,prompt = question.get('answer'),question.get('prompt')
    if not isinstance(calculation,dict) or not isinstance(answer,str) or not isinstance(prompt,str):
        return None
    try:
        expression = normalize_calculation(calculation.get('expression'))
        actual = expected_calculation(expression,prompt)
        supplied = Fraction(str(calculation.get('answer')))
    except (ValueError,TypeError,ZeroDivisionError):
        return None
    tokens = list(NUMBER.finditer(answer))
    if not tokens:
        return None
    candidates = []
    for token in tokens:
        raw = token[0].replace(',','')
        try:
            value = Fraction(raw)
        except (ValueError,ZeroDivisionError):
            continue
        # A single leading result can retain its unit and explanation. Numbers in
        # the middle of success criteria are not assumed to be computed answers.
        prefix = answer[:token.start()].strip()
        leading = len(tokens)==1 and re.fullmatch(r'(?:(?:answer|result)(?:\s+is)?\s*[:=]?\s*|(?:about|approximately)\s+)?[$£€]?\s*',prefix,re.I)
        percent = bool(re.match(r'\s*%',answer[token.end():]))
        close = value==actual
        if '.' in raw and '/' not in raw:
            places = len(raw.split('.',1)[1])
            if places<=4:
                close = close or value==expected_calculation(expression,f'Round to {places} decimal places.')
        if leading or (percent and close):
            candidates.append((token,value))
    if len(candidates)!=1:
        return None  # Multi-step or ambiguous prose still needs semantic repair.
    token,value = candidates[0]
    if supplied==actual and value==actual:
        return None
    result = deepcopy(page)
    target = next(q for q in result['exercise']['questions'] if str(q.get('id'))==question_id)
    formatted = format_result(actual,prompt)
    target['calculation'] = {**calculation,'expression':expression,'answer':formatted}
    target['answer'] = answer[:token.start()]+formatted+answer[token.end():]
    return result
