"""Distinguish statement reasoning paths from the geometric wall-and-star maze tool."""
import re
from html.parser import HTMLParser


def is_statement_maze(page: dict, *, planning: bool = False) -> bool:
    """Require routing, factual judgement and statement selection in the actual task intent."""
    fields=('learning_goal','activity_concept') if planning else ('goal','directions')
    values=[page.get(field,'') for field in fields]
    if not planning:
        for field,key in (('captions','text'),('questions','prompt')):
            items=page.get(field,[])
            if isinstance(items,list):
                values.extend(item.get(key,'') for item in items if isinstance(item,dict))
    text=' '.join(value for value in values if isinstance(value,str))
    return bool(re.search(r'\b(?:maze|path|route|trail|checkpoints?)\b',text,re.I)
        and re.search(r'\b(?:facts?|factual|opinions?|verifiable|true|false)\b',text,re.I)
        and re.search(r'\b(?:statements?|claims?|checkpoints?)\b',text,re.I)
        and re.search(r'\b(?:choos\w*|select\w*|identif\w*|recogniz\w*|distinguish\w*|avoid|only|correct|incorrect)\b',text,re.I))


def has_printed_statement_path(page: dict) -> bool:
    """Check printed route prerequisites, leaving unique-route correctness to content review."""
    return not statement_path_issues(page)


def statement_path_issues(page: dict) -> list[str]:
    """Inspect actual bound text, including captions; never treat image prompts as printed data."""
    exercise=page.get('exercise') or {}
    if not (page.get('exercise_binding') and isinstance(exercise,dict)
            and exercise.get('render_mode')=='authored' and exercise.get('mechanic')=='statement_path'):
        return ['Use a compiled authored statement_path exercise.']
    issues=[]
    sources=exercise.get('stimuli')
    if not isinstance(sources,list) or len(sources)<2 or any(not isinstance(s,dict)
            or not isinstance(s.get('text'),str) or not s['text'].strip() for s in sources):
        issues.append('Declare at least two complete printed statement cards in exercise.stimuli.')
    parts=[];parser=HTMLParser(convert_charrefs=True)
    parser.handle_data=parts.append;parser.feed(page.get('html',''));parser.close()
    wording=' '.join(' '.join(parts).split())
    if not re.search(r'\b(?:START|BEGIN|ENTRY|ENTRANCE)\b',wording,re.I):
        issues.append('Print a starting endpoint in a source card, caption or directions (e.g. START or BEGIN).')
    if not re.search(r'\b(?:FINISH|EXIT|END)\b',wording,re.I):
        issues.append('Print a finishing endpoint in a source card, caption or directions (e.g. FINISH or END).')
    wording_links=re.search(r'\b(?:(?:go|move|continue|proceed|return|advance|head|jump|leads?|connects?)\s+(?:to|towards?)|next\s*(?:checkpoint|node|step|stop|card|statement)?\s*(?:[:=]|is\b|[A-Z0-9]\b))',wording,re.I)
    arrow_links=re.search(r'\b[\w-]+(?:\s+[\w-]+){0,4}\s*(?:→|⇒|➜|⟶|->|=>)\s*[\w-]+(?:\s+[\w-]+){0,4}\b',wording,re.I)
    if not (wording_links or arrow_links):
        issues.append('Print explicit next-step links, e.g. A → B, Next: B or move to checkpoint B.')
    art=r'(?:images?|illustrations?|pictures?|artwork|photos?)'
    depends_on_art=(re.search(r'\b(?:trace|follow|find|choose|navigate|read)\b[^.!?]{0,45}\b(?:path|route|maze|trail|checkpoints?)\b[^.!?]{0,30}\b(?:in|on|through|from)\b[^.!?]{0,25}\b'+art+r'\b',wording,re.I)
        or re.search(r'\b(?:use|read|look at|refer to)\b[^.!?]{0,25}\b'+art+r'\b[^.!?]{0,50}\b(?:trace|follow|find|navigate)\b[^.!?]{0,25}\b(?:path|route|maze|checkpoints?)\b',wording,re.I))
    if depends_on_art:
        issues.append('Use the printed text cards and connections for routing; do not require tracing a route in AI artwork.')
    return issues
