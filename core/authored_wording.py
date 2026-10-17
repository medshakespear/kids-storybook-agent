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
        # A pure block wrapper is not one paragraph. Keep each original p/div
        # intact so a scoped repair can bind it without truncating its neighbors.
        block_children=any(isinstance(c,dict) and c.get('tag') in {'p','div','section'} for c in node['children'])
        own_text=any(isinstance(c,str) and c.strip() for c in node['children'])
        if not inside and node['tag'] in CONTAINERS and not (block_children and not own_text):
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


def bind_printed_context(page: dict, exercise: dict, config: dict) -> None:
    """Register complete already-printed declarative paragraphs without another AI call.

    Only opted-in authored workbooks qualify. Never take words from canonical
    slots, data tables, questions, labels, media or handwriting surfaces. Every
    promoted character and the existing question/key remain unchanged.
    """
    if not config.get('simple_exercises_only') or exercise.get('render_mode')!='authored':return
    parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
    if parser.stack:return
    from core.context_recovery import contextual_text
    from core.print_grid import literal_html
    stimuli=exercise.get('stimuli',[])
    if not isinstance(stimuli,list):return
    known={normalized(str(exercise.get(k,''))) for k in ('directions','passage')}
    known.add(normalized(str(page.get('_recovery_title',''))))
    for field,key in (('stimuli','text'),('captions','text'),('questions','prompt')):
        known.update(normalized(str(item.get(key,''))) for item in exercise.get(field,[]) if isinstance(item,dict))
    ids={item.get('id') for item in stimuli if isinstance(item,dict)}
    ids.update(item.get('id') for item in exercise.get('captions',[]) if isinstance(item,dict))
    changed=False
    def visit(node,protected=False):
        """Keep actual table cells and complete paragraph boundaries distinct."""
        nonlocal changed
        if isinstance(node,str) or 'comment' in node:return
        slot=dict(node['attrs']).get('data-content')
        table=(node['tag']=='table' and (any(isinstance(c,dict) and c.get('tag')=='th' for c in node['children'])
               or bool(re.search(r'<th\b',literal_html(node))) or len(re.findall(r'<tr\b',literal_html(node)))>1))
        protected=protected or bool(slot) or table
        if not protected and node['tag'] in {'p','div','section'}:
            pieces=[parser.plain_text(c) for c in node['children']]
            leaf=not any(isinstance(c,dict) and c.get('tag') in {'p','div','section'} for c in node['children'])
            text=''.join(pieces).strip() if leaf and all(p is not None for p in pieces) else ''
            own_style=dict(node['attrs']).get('style','') or ''
            commands=any(instruction_start(re.sub(r'^(?:next|finally)[,:]?\s+','',part,flags=re.I))
                         for part in re.split(r'(?<=[.!?;:])\s+|\band\s+|,\s+',text))
            if (80<=len(text)<=650 and normalized(text) not in known and contextual_text(text)
                    and not commands and not instruction_start(text) and not re.search(r'(?:^|;)\s*(?:min-|max-)?height\s*:',own_style,re.I)):
                # Passage avoids inventing a source label for a single raw paragraph.
                if not str(exercise.get('passage','') or '').strip():
                    exercise['passage']=text;target='passage'
                elif len(stimuli)<config.get('stimulus_limit',4):
                    sid=next(f'printed_context_{n}' for n in range(1,len(ids)+2) if f'printed_context_{n}' not in ids)
                    ids.add(sid);stimuli.append({'id':sid,'label':'Reading Context','text':text});exercise['stimuli']=stimuli
                    target='stimulus_'+sid
                else:return
                node['attrs'].append(('data-content',target));node['children']=[]
                known.add(normalized(text));changed=True;return
        for child in node['children']:visit(child,protected)
    for node in parser.root:visit(node)
    if changed:page['html']=''.join(literal_html(n) for n in parser.root)
