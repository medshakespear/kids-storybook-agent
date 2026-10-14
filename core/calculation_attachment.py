"""Remove stray arithmetic metadata only from clearly nonnumeric conceptual questions."""
import re


def label_matching_text(prompt: str) -> str | None:
    """Identify label-only matching instructions; numbered ranges are references, not subtraction."""
    if not isinstance(prompt,str) or not re.search(r'\b(?:match|matching|pair|connect)\b',prompt,re.I):
        return None
    if not re.search(r'\b(?:claims?|sources?|cards?|statements?|labels?)\b',prompt,re.I):
        return None
    ranges=list(re.finditer(r'\((?:[1-9]\d?\s*[-–]\s*[1-9]\d?|[A-Z]\s*[-–]\s*[A-Z])\)',prompt))
    if not ranges:
        return None
    text=re.sub(r'\((?:[1-9]\d?\s*[-–]\s*[1-9]\d?|[A-Z]\s*[-–]\s*[A-Z])\)','',prompt)
    quantity=r'calculate|compute|solve|evaluate|subtract|add|multiply|divide|totals?|sums?|differences?|percent(?:age)?|how many|how much|count|average|mean|median|mode|ratio|fraction|rate|remaining|amount|quantity|measurements?|weights?|lengths?|zero|one|two|three|four|five|six|seven|eight|nine|ten|half|double|twice'
    if re.search(r'\d|[+×÷*/=]|\b(?:'+quantity+r')\b',text,re.I):
        return None
    # A numeric range must be introduced explicitly as a printed identifier.
    for match in ranges:
        if match[0][1].isdigit() and not re.search(r'\b(?:numbers?|labels?|sources?|cards?)\s*$',prompt[:match.start()],re.I):
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
