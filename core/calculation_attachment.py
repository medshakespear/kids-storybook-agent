"""Remove stray arithmetic metadata only from clearly nonnumeric conceptual questions."""
import re


def detach_conceptual_calculation(question: dict) -> None:
    """Keep prompt/answer/workspace intact; leave quantitative or ambiguous tasks untouched."""
    if not isinstance(question.get('calculation'),dict):
        return
    prompt, answer = question.get('prompt'), question.get('answer')
    if not isinstance(prompt,str) or not isinstance(answer,str):
        return
    conceptual = re.match(r'^(?:why\b|explain\b|describe\b|name\b|which (?:[a-z-]+\s+){0,2}(?:part|component|material|action|element|factor|structure|support|pillar|design|option|object)\b|what (?:part|component|happens|causes|structure|support|design)\b)',prompt.strip(),re.I)
    quantity = r'\d|[+×÷*/=]|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|half|quarter|double|triple|twice|how many|how much|number|amount|quantity|total|sum|difference|count|calculate|solve|percent|fraction|ratio|rate|remaining|remain|left over|more than|less than)\b'
    if conceptual and not re.search(quantity,prompt+' '+answer,re.I):
        question.pop('calculation')
