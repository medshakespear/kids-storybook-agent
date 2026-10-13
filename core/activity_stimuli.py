"""Keep source excerpts and scenarios separate from short visual captions."""
import re


def source_id(value: str) -> str:
    """Remove only the reserved source-slot namespace, including repeated copies."""
    while value.startswith('stimulus_'):
        value=value[len('stimulus_'):]
    return value


def normalize_stimulus_ids(page: dict, exercise: dict) -> None:
    """Align declared source IDs and HTML references without changing any source text.

    Refuse collisions instead of selecting between two evidence cards. Unknown
    references remain unknown and still require an explicitly supplied source.
    """
    from copy import deepcopy
    import html
    from core.content_binding import CanonicalTextContainers
    stimuli=exercise.get('stimuli',[])
    if not isinstance(stimuli,list):
        raise ValueError('Exercise stimuli must be a JSON list')
    normalized=[];seen=set();changed=False
    for item in stimuli:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str):
            normalized.append(item)
            continue  # The existing shared-spec validator reports malformed entries.
        sid=source_id(item['id'])
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,23}',sid):
            normalized.append(item)
            continue
        if sid in seen:
            raise ValueError(f'Source stimulus IDs collide after namespace normalization: {sid}')
        seen.add(sid)
        copy=deepcopy(item);copy['id']=sid;normalized.append(copy)
        changed=changed or sid!=item['id']
    parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
    if parser.stack:
        raise ValueError('Exercise layout tags must be balanced')

    def visit(node):
        """Rewrite actual declared source attributes, never words inside source cards."""
        nonlocal changed
        if isinstance(node,str) or 'comment' in node:
            return
        attrs=[]
        for key,value in node['attrs']:
            if key=='data-content' and isinstance(value,str) and value.startswith('stimulus_'):
                sid=source_id(value)
                if sid in seen:
                    canonical='stimulus_'+sid
                    changed=changed or value!=canonical
                    value=canonical
            attrs.append((key,value))
        node['attrs']=attrs
        for child in node['children']:
            visit(child)

    def render(node):
        """Serialize the retained tree literally, preserving all graphics and work areas."""
        if isinstance(node,str):
            return html.escape(node,quote=False)
        if 'comment' in node:
            return '<!--'+node['comment']+'-->'
        attrs=' '.join(f'{k}="{html.escape(v or "",quote=True)}"' for k,v in node['attrs'])
        start=f'<{node["tag"]} {attrs}>'
        return start if node['tag'] in {'img','br'} else start+''.join(render(c) for c in node['children'])+f'</{node["tag"]}>'

    for node in parser.root:
        visit(node)
    if changed:
        exercise['stimuli']=normalized
        page['html']=''.join(render(node) for node in parser.root)


def stimulus_capacity(config: dict) -> int:
    """Return the explicitly configured short-source capacity with a bounded legacy default."""
    limit = config.get('stimulus_limit',4)
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError('Source stimulus limit must be between 1 and 8')
    return limit


def merge_missing_sources(original: dict, correction: dict) -> dict:
    """Adopt missing authored sources and their layout without rewriting retained task data."""
    from copy import deepcopy
    from html.parser import HTMLParser
    original=deepcopy(original);correction=deepcopy(correction)
    normalize_stimulus_ids(original,original['exercise'])
    if isinstance(correction,dict) and isinstance(correction.get('exercise'),dict) and isinstance(correction.get('html'),str):
        normalize_stimulus_ids(correction,correction['exercise'])
    exercise = original['exercise']
    old = exercise.get('stimuli',[])
    new = correction.get('exercise',{}).get('stimuli') if isinstance(correction,dict) and isinstance(correction.get('exercise'),dict) else None
    if not isinstance(old,list) or not isinstance(new,list) or not isinstance(correction.get('html'),str):
        raise ValueError('Missing-source repair must return complete HTML and exercise.stimuli as a list')
    retained = {s.get('id') for s in old if isinstance(s,dict)}
    references = set()
    parser = HTMLParser(convert_charrefs=True)
    def collect(tag,attrs):
        """Collect only explicit source references from the retained activity."""
        slot = dict(attrs).get('data-content','') or ''
        if slot.startswith('stimulus_'):
            references.add(source_id(slot))
    parser.handle_starttag = collect
    parser.handle_startendtag = collect
    parser.feed(original['html']); parser.close()
    missing = references - retained
    additions=[]
    for sid in sorted(missing):
        matches=[s for s in new if isinstance(s,dict) and s.get('id')==sid]
        if len(matches)!=1 or not isinstance(matches[0].get('text'),str) or not matches[0]['text'].strip():
            raise ValueError(f'Missing-source repair needs one nonempty source for {sid}; never delete its slot')
        additions.append(deepcopy(matches[0]))
    result = deepcopy(original)
    result['html'] = correction['html']
    result['exercise']['stimuli'] = deepcopy(old) + additions
    normalize_stimulus_ids(result,result['exercise'])
    return result


def prepare_stimuli(page: dict, exercise: dict) -> list[dict]:
    """Move complete overlong caption text into source blocks without truncating it.

    Only text already present in the shared specification is moved. The layout's
    corresponding slot is renamed; question wording, answers and data stay intact.
    """
    normalize_stimulus_ids(page,exercise)
    stimuli = exercise.get('stimuli', [])
    if not isinstance(stimuli, list):
        raise ValueError('Exercise stimuli must be a JSON list')
    captions = exercise.get('captions', [])
    if not isinstance(captions, list):
        return stimuli
    retained = []
    ids = {item.get('id') for item in stimuli if isinstance(item,dict)}
    for caption in captions:
        if (isinstance(caption,dict) and isinstance(caption.get('text'),str)
                and 120 < len(caption['text'].strip())):
            cid = caption.get('id')
            if not isinstance(cid,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,23}',cid):
                retained.append(caption)
                continue
            if cid in ids:
                raise ValueError('Source stimulus IDs must not collide with migrated caption IDs')
            stimuli.append(dict(caption))
            ids.add(cid)
            # Both prefix conventions are accepted elsewhere for declared IDs.
            pattern = r'(\bdata-content\s*=\s*)([\'\"])(?:caption_)?'+re.escape(cid)+r'\2'
            page['html'] = re.sub(pattern,lambda m:m[1]+m[2]+'stimulus_'+cid+m[2],page['html'])
        else:
            retained.append(caption)
    exercise['captions'] = retained
    exercise['stimuli'] = stimuli
    normalize_stimulus_ids(page,exercise)
    return exercise['stimuli']


def source_density_repair(draft: dict, prompt: str, error: str) -> str | None:
    """Request content revision when an opt-in mixed source page cannot fit unchanged."""
    target = re.search(r'combined passage and stimuli target <=(\d+) words',prompt)
    exercise = draft.get('exercise') if isinstance(draft,dict) else None
    if not target or not error.startswith(('Design overflow:', 'Design content extends outside printable bounds:')) or not isinstance(exercise,dict):
        return None
    texts = [exercise.get('passage','')]
    for field in ('stimuli','captions'):
        values = exercise.get(field,[])
        if isinstance(values,list):
            texts += [s.get('text','') for s in values if isinstance(s,dict)
                      and (field=='stimuli' or len(str(s.get('text',''))) > 120)]
    words = sum(len(text.split()) for text in texts if isinstance(text,str))
    limit = int(target[1])
    if words <= limit:
        return None
    return (f'This mixed activity has {words} source/passage words and cannot fit unchanged. '
            f'Return a complete revised exercise and layout targeting {limit} combined source words, '
            'not an HTML-only repair. Shorten source phrasing while retaining every fact, quantity '
            'and distinction required by the printed questions. Keep the planned title, mechanic, '
            'learning goal, substantive images, readable font and response space. Realign the shared '
            'answer criteria to the revised sources. Use stimuli for excerpts and short captions for '
            'labels. Do not delete questions, invent evidence or shrink typography to force a fit.')
