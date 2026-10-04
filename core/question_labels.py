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
    if not isinstance(prompt,str) or type(space) not in {int,float}:
        return layout
    reasoning = (space>=5 and re.match(r'^(?:explain|describe|justify|predict|suggest|discuss|why|how (?:would|could|can)|what (?:would|could|might))\b',prompt,re.I))
    explicit_math = (isinstance(question.get('calculation'),dict) and
                     re.match(r'^(?:what is|calculate|solve|evaluate)\b',prompt,re.I) and
                     re.search(r'\d\s*[+−×÷*/-]\s*\d',prompt))
    creative = (space>=5 and re.match(r'^(?:draw|design|create|invent|color|colour|decorate|write|make)\b',prompt,re.I) and
                not re.search(r'\b(?:count|match|connect|choose|correct|circle|find|trace|total|answer|sum|difference|which|complete|solve|calculate)\b|how many|number of',prompt,re.I))
    if not (reasoning or explicit_math or creative):
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


def remove_literal_exact_duplicate(exercise: dict, layout: str) -> str:
    """Remove only a zero-workspace literal repeat of computed puzzle instructions."""
    from core.task_visuals import build_visual
    from core.content_binding import CanonicalTextContainers
    import html
    questions, visual = exercise.get('questions'), exercise.get('visual')
    if not isinstance(questions,list) or not isinstance(visual,dict):
        return layout
    reserved=str(visual.get('question'))
    matches=[q for q in questions if isinstance(q,dict) and str(q.get('id'))==reserved]
    if len(matches)!=1:
        return layout
    question=matches[0]
    if question.get('space_mm',0)!=0 or question.get('calculation') is not None:
        return layout
    def normalize(value):
        """Compare instruction text while ignoring only case, whitespace and its number."""
        return re.sub(r'^\d+\.\s*','', ' '.join(str(value).split())).strip().casefold()
    svg,_=build_visual(visual)
    labels=[html.unescape(v) for v in re.findall(r'<text\b[^>]*>(.*?)</text>',svg)]
    allowed={normalize(v) for v in labels[:2]}|{normalize(' '.join(labels[:2]))}
    if normalize(question.get('prompt','')) not in allowed:
        return layout
    parser=CanonicalTextContainers({});parser.feed(layout);parser.close()
    slots=[]
    def inspect(node):
        """Locate one canonical duplicate slot without inferring or removing other tasks."""
        if isinstance(node,str) or 'comment' in node:
            return
        if dict(node['attrs']).get('data-content')=='question_'+reserved:
            slots.append(node)
        for child in node['children']:
            inspect(child)
    for node in parser.root:
        inspect(node)
    if len(slots)!=1:
        return layout
    target=slots[0]
    def text_only(node, root=False):
        """Never remove media, response panels, independent slots or comments."""
        if isinstance(node,str):
            return node
        if 'comment' in node or node['tag'] in {'img','table'}:
            return None
        attrs=dict(node['attrs'])
        if not root and any(k.startswith('data-') for k in attrs):
            return None
        if re.search(r'(?:^|;)\s*(?:height|min-height|max-height)\s*:',attrs.get('style',''),re.I):
            return None
        parts=[text_only(child) for child in node['children']]
        return None if any(v is None for v in parts) else ''.join(parts)
    value=text_only(target,True)
    if value is None or (value.strip() and normalize(value)!=normalize(question['prompt'])):
        return layout
    def render(node):
        """Serialize all retained nodes and omit the one proven duplicate."""
        if node is target:
            return ''
        if isinstance(node,str):
            return html.escape(node,quote=False)
        if 'comment' in node:
            return '<!--'+node['comment']+'-->'
        attrs=' '.join(f'{key}="{html.escape(value or "",quote=True)}"' for key,value in node['attrs'])
        start=f'<{node["tag"]} {attrs}>'
        return start if node['tag'] in {'img','br'} else start+''.join(render(c) for c in node['children'])+f'</{node["tag"]}>'
    exercise['questions']=[q for q in questions if q is not question]
    return ''.join(render(n) for n in parser.root)
