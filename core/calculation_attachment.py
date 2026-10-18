"""Remove stray arithmetic metadata only from clearly nonnumeric conceptual questions."""
import re


def label_matching_text(prompt: str) -> str | None:
    """Identify label-only matching instructions; numbered ranges are references, not subtraction."""
    if not isinstance(prompt,str) or not re.search(r'\b(?:match|matching|pair|connect)\b',prompt,re.I):
        return None
    if not re.search(r'\b(?:claims?|sources?|cards?|statements?|labels?|terms?|items?|components?|materials?|descriptions?)\b',prompt,re.I):
        return None
    # Parentheses are optional, but the adjacent noun must still identify
    # labels. Never strip a numeric operation simply because this is matching.
    range_pattern=r'(?<![\w.])(?:\((?:[1-9]\d?\s*[-–]\s*[1-9]\d?|[A-Z]\s*[-–]\s*[A-Z])\)|[1-9]\d?\s*[-–]\s*[1-9]\d?|[A-Z]\s*[-–]\s*[A-Z])(?!\w|\.\d)'
    ranges=list(re.finditer(range_pattern,prompt))
    if not ranges:
        return None
    text=re.sub(range_pattern,'',prompt)
    quantity=r'calculate|compute|solve|evaluate|subtract|add|multiply|divide|totals?|sums?|differences?|percent(?:age)?|how many|how much|count|average|mean|median|mode|ratio|fraction|rate|remaining|amount|quantity|measurements?|weights?|lengths?|zero|one|two|three|four|five|six|seven|eight|nine|ten|half|double|twice'
    if re.search(r'\d|[+×÷*/=]|\b(?:'+quantity+r')\b',text,re.I):
        return None
    # A numeric range must be introduced explicitly as a printed identifier.
    for match in ranges:
        if match[0].lstrip('(')[0].isdigit() and not re.search(r'\b(?:numbers?|labels?|sources?|cards?|terms?|items?|components?|materials?|descriptions?|headings?)\s*$',prompt[:match.start()],re.I):
            return None
    return text


def detach_conceptual_calculation(question: dict) -> None:
    """Keep prompt/answer/workspace intact; leave quantitative or ambiguous tasks untouched."""
    if not isinstance(question.get('calculation'),dict):
        return
    prompt, answer = question.get('prompt'), question.get('answer')
    if not isinstance(prompt,str) or not isinstance(answer,str):
        return
    if label_matching_text(prompt) is not None:
        question.pop('calculation')
        return
    conceptual = re.match(r'^(?:why\b|explain\b|describe\b|name\b|which (?:[a-z-]+\s+){0,2}(?:part|component|material|action|element|factor|structure|support|pillar|design|option|object)\b|what (?:part|component|happens|causes|structure|support|design)\b)',prompt.strip(),re.I)
    quantity = r'\d|[+×÷*/=]|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|half|quarter|double|triple|twice|how many|how much|number|amount|quantity|total|sum|difference|count|calculate|solve|percent|fraction|ratio|rate|remaining|remain|left over|more than|less than)\b'
    if conceptual and not re.search(quantity,prompt+' '+answer,re.I):
        question.pop('calculation')


def writing_length_text(prompt: str) -> str:
    """Exclude a requested sentence count from arithmetic detection, preserving the printed prompt."""
    if not isinstance(prompt,str) or not re.search(r'\b(?:write|explain|explanation|describe|paragraph)\b',prompt,re.I):return prompt
    return re.sub(r'\(?\b\d+(?:\s*[-–]\s*\d+)?\s+sentences?\b\)?','',prompt,flags=re.I)


def detach_writing_result(question: dict) -> None:
    """Remove an isolated template result from a clearly nonnumeric explanation task.

    Sentence-length requests are writing instructions, not subtraction. Require
    a matching declared numeric template result and a retained qualitative
    success criterion; never reinterpret quantitative questions or source facts.
    """
    from fractions import Fraction
    from core.exercise_quality import calculate,normalize_calculation
    prompt,answer=question.get('prompt'),question.get('answer')
    calc=question.get('calculation')
    if not isinstance(prompt,str) or not isinstance(answer,str) or not isinstance(calc,dict):return
    writing=writing_length_text(prompt)
    if not re.search(r'\bwrite\b.*\bexplanation\b.*\bwhy\b',writing,re.I):return
    quantitative=r'\d|[+×÷*/=]|\b(?:calculate|count|total|sum|difference|perimeter|area|ratio|rate|percent|fraction|measurement|quantity|how many|how much|number|amount)\b'
    if re.search(quantitative,writing,re.I):return
    match=re.fullmatch(r'Result is (-?\d+(?:\.\d+)?(?:/\d+)?)\.\s+((?:Explanation should|Accept an explanation)\b[\s\S]+)',answer,re.I)
    if not match or re.search(quantitative,match[2],re.I):return
    try:
        value=Fraction(match[1])
        if value!=Fraction(str(calc.get('answer'))) or value!=calculate(normalize_calculation(calc.get('expression'))):return
    except (ValueError,TypeError,ZeroDivisionError):return
    question.pop('calculation')
    question['answer']=match[2]
