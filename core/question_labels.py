"""Repair reserved puzzle labels only for unambiguous additional creative actions."""
import re


def renumber_open_exact_question(exercise: dict, layout: str) -> str:
    """Keep an additional open action and its work area while moving its colliding label."""
    questions = exercise.get('questions')
    visual = exercise.get('visual')
    if not isinstance(questions,list) or not isinstance(visual,dict) or not isinstance(layout,str):
        return layout
    reserved = str(visual.get('question'))
    labels = [str(q.get('id')) for q in questions if isinstance(q,dict)]
    if len(labels)!=len(questions) or len(set(labels))!=len(labels):
        return layout
    matches = [q for q in questions if str(q.get('id'))==reserved]
    if len(matches)!=1:
        return layout
    question = matches[0]
    prompt = question.get('prompt')
    space = question.get('space_mm')
    if not isinstance(prompt,str) or type(space) not in {int,float} or space<5:
        return layout
    if not re.match(r'^(?:draw|design|create|invent|color|colour|decorate|write|make)\b',prompt,re.I):
        return layout
    if re.search(r'\b(?:count|match|connect|choose|correct|circle|find|trace|total|answer|sum|difference|which|complete|solve|calculate)\b|how many|number of',prompt,re.I):
        return layout  # Closed/duplicate puzzle actions need a semantic repair.
    if not re.fullmatch(r'[1-9]\d?',reserved):
        return layout
    slot = re.compile(r'''(\bdata-content\s*=\s*)(["'])question_'''+re.escape(reserved)+r'''\2''')
    if len(slot.findall(layout))!=1:
        return layout
    unused = next((str(n) for n in range(1,31) if str(n) not in set(labels)|{reserved}),None)
    if unused is None:
        return layout
    question['id'] = unused
    return slot.sub(lambda m:m[1]+m[2]+'question_'+unused+m[2],layout)
