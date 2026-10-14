"""Distinguish statement reasoning paths from the geometric wall-and-star maze tool."""
import re


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
    """Require canonical printed source cards with endpoints and explicit routing wording."""
    exercise=page.get('exercise') or {}
    if not (page.get('exercise_binding') and isinstance(exercise,dict)
            and exercise.get('render_mode')=='authored' and exercise.get('mechanic')=='statement_path'):
        return False
    sources=exercise.get('stimuli')
    if not isinstance(sources,list) or len(sources)<2 or any(not isinstance(s,dict)
            or not isinstance(s.get('text'),str) or not s['text'].strip() for s in sources):
        return False
    wording=' '.join(source['text'] for source in sources)
    tasks=' '.join([exercise.get('directions','')]+[q.get('prompt','') for q in exercise.get('questions',[])])
    if re.search(r'\b(?:images?|illustrations?|pictures?|artwork|photos?)\b',tasks,re.I):
        return False  # A printed route must never be read from generated pixels.
    return bool(re.search(r'\bSTART\b',wording,re.I) and re.search(r'\b(?:FINISH|EXIT)\b',wording,re.I)
        and re.search(r'\b(?:(?:go|continue|proceed|return)\s+to|next\s+(?:checkpoint|node|step|stop))\b',wording,re.I))
