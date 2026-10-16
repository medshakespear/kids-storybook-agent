"""Bind already printed authored prose without shortening it into decorative captions."""
import re

from core.content_binding import CanonicalTextContainers,CONTAINERS

ACTION_GROUPS=(('read','review','study','examine','look'),
               ('rewrite','transform','rephrase','restate','convert'),
               ('draw','sketch','illustrate'),('write','record','list'),
               ('sort','classify','categorize','group'),('match','pair','connect'),
               ('explain','describe','justify'),('compare','contrast'),
               ('calculate','solve','compute','count'),('choose','select','circle'),
               ('design','create','invent'),('identify','find','locate'),('measure',),('complete',))
ACTION_MAP={word:index for index,group in enumerate(ACTION_GROUPS) for word in group}
ACTION_PATTERN='|'.join(ACTION_MAP)


def instruction_start(text: str) -> bool:
    """Keep imperative paragraphs out of factual-passage binding."""
    return bool(re.match(r'^(?:(?:please|now|then)\s+)?(?:'+ACTION_PATTERN+r')\b',text,re.I))


def normalized(value: str) -> str:
    """Compare complete printed wording independent of case and whitespace."""
    return ' '.join(value.split()).casefold()


def raw_paragraphs(page: dict) -> set[str]:
    """Read complete unslotted text containers without consuming assets or writing areas."""
    parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
    if parser.stack:
        raise ValueError('Exercise layout tags must be balanced')
    exercise=page['exercise']
    known={normalized(str(exercise.get(k,''))) for k in ('directions','passage')}
    expected_title=normalized(str(page.get('_recovery_title','')))
    known.add(expected_title)
    for field,text_key in (('captions','text'),('stimuli','text'),('questions','prompt')):
        for item in exercise.get(field,[]):
            if isinstance(item,dict) and isinstance(item.get(text_key),str):
                text=item[text_key];known.add(normalized(text))
                if field=='questions': known.add(normalized(str(item.get('id'))+'. '+text))
    values=set()

    def visit(node,inside=False):
        """Take only complete literal blocks outside existing canonical slots."""
        if isinstance(node,str) or 'comment' in node:
            return
        inside=inside or any(k=='data-content' for k,_ in node['attrs'])
        if not inside and node['tag'] in CONTAINERS:
            pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in node['children']]
            if all(p is not None for p in pieces):
                text=normalized(''.join(pieces))
                blank=bool(re.fullmatch(r'(?:name|date)\s*:\s*[_\s]*|[_\s|]+|\[[_\s]*\]',text))
                combined=re.fullmatch(r'(name|date)\s*:\s*[_\s]{3,}\s+(name|date)\s*:\s*[_\s]{3,}',text)
                blank=blank or bool(combined and combined[1]!=combined[2])
                title=re.sub(r'^(?:page|activity)\s+#?\d+\s*[:.\-–—]\s*','',text)
                canonical_title=(node['tag'] in {'h1','h2','h3','h4'} and title==expected_title
                                  or (node['tag']=='h1' and len(parser.primary_headings)==1
                                                   and not parser.explicit_title))
                if text and text not in known and not blank and not canonical_title:
                    values.add(text)
                    return
        for child in node['children']:
            visit(child,inside)

    for node in parser.root:
        visit(node)
    return values


def complete_additions(value: str, candidates: set[str]) -> set[str] | None:
    """Accept only concatenations of complete retained blocks, never fragments or paraphrases."""
    memo={}

    def split(rest):
        """Match whole paragraphs with memoized bounded suffix processing."""
        if not rest:
            return set()
        if rest in memo:
            return memo[rest]
        memo[rest]=None
        for text in sorted(candidates,key=len,reverse=True):
            if rest==text:
                memo[rest]={text};break
            if rest.startswith(text+' '):
                tail=split(rest[len(text)+1:])
                if tail is not None:
                    memo[rest]={text}|tail;break
        return memo[rest]

    return split(value)


def retained_instruction(text: str, exercise: dict) -> bool:
    """Accept already printed directions only for actions present in the retained task."""
    mapping=ACTION_MAP
    verbs=ACTION_PATTERN
    actions=re.findall(r'(?:^|[.!?;]\s+)(?:(?:please|now|then)\s+)?('+verbs+r')\b',text,re.I)
    if not actions or not instruction_start(text):
        return False
    canonical=' '.join(str(exercise.get(k,'')) for k in ('directions','goal','mechanic')).replace('_',' ')
    canonical+=' '+' '.join(str(q.get('prompt','')) for q in exercise.get('questions',[]) if isinstance(q,dict))
    declared={mapping[word.lower()] for word in re.findall(r'\b('+verbs+r')\b',canonical,re.I)}
    if any(mapping[word.lower()] not in declared|{0} for word in actions):
        return False  # Do not authorize a new action with no retained answer criterion.
    from core.prompt_recovery import numeric_values
    # Complete wording is preserved, and a directions-only repair may not add
    # numerical requirements absent from the existing task/source specification.
    for field in ('stimuli','captions'):
        canonical+=' '+' '.join(str(item.get('text','')) for item in exercise.get(field,[]) if isinstance(item,dict))
    return set(numeric_values(text)).issubset(numeric_values(canonical))


def merge_authored_wording(original: dict, correction: dict) -> dict:
    """Adopt lossless prose bindings while pinning questions, keys, sources and artwork."""
    from core.creative_generator import merge_layout_repair
    if (original['exercise'].get('render_mode')!='authored' or not isinstance(correction,dict)
            or not isinstance(correction.get('exercise'),dict)):
        raise ValueError('Authored wording repair requires HTML and a shared authored exercise')
    candidates=raw_paragraphs(original)
    from core.context_recovery import contextual_text
    prose={text for text in candidates if contextual_text(text) and not instruction_start(text)}
    instructions={text for text in candidates if retained_instruction(text,original['exercise'])}
    adopted={};covered=set()
    for field in ('directions','passage'):
        old=original['exercise'].get(field,'') or ''
        new=correction['exercise'].get(field,old)
        if not isinstance(new,str) or not isinstance(old,str):
            raise ValueError('Authored wording repair needs text directions and passage')
        before,after=normalized(old),normalized(new)
        if before==after:
            continue
        if before and not after.startswith(before+' '):
            raise ValueError('Authored wording repair must retain existing directions and passage verbatim')
        added=after[len(before):].strip() if before else after
        blocks=complete_additions(added,prose|instructions if field=='directions' else prose)
        if blocks is None:
            raise ValueError('Authored wording repair must bind complete original paragraphs; no truncation or new wording')
        adopted[field]=new;covered.update(blocks)
    try:
        result=merge_layout_repair(original,correction)
    except ValueError as exc:
        raise ValueError('Authored wording repair: '+str(exc)) from None
    result['exercise'].update(adopted)
    old_ids={c.get('id') for c in original['exercise'].get('captions',[]) if isinstance(c,dict)}
    for caption in result['exercise'].get('captions',[]):
        if isinstance(caption,dict) and isinstance(caption.get('text'),str):
            from core.content_binding import instruction_heading
            retained_heading=instruction_heading(caption['text']) and normalized(caption['text']) in candidates
            if caption.get('id') not in old_ids and re.match(
                    r'^(?:(?:please|now|then)\s+)?(?:draw|write|count|sort|match|pair|circle|find|trace|'
                    r'explain|describe|calculate|solve|choose|complete|help|design|create|compare|transform|'
                    r'identify|read|list|rewrite|record|investigate|measure)\b',caption['text'].strip(),re.I) and not retained_heading:
                raise ValueError('Authored wording repair must not hide additional commands in captions')
            covered.add(normalized(caption['text']))
    remaining=raw_paragraphs(result)
    if not candidates.issubset(covered|remaining):
        raise ValueError('Authored wording repair cannot discard original unbound paragraphs or headings')
    return result
