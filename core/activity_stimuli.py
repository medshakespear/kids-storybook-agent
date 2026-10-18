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
    sources={s['id']:s for s in normalized if isinstance(s,dict) and s.get('id') in seen}
    captions=deepcopy(exercise.get('captions',[]))
    # Only generic source-card/text aliases can bind by elimination. Do not
    # guess identities for named cards, missing evidence, or competing sources.
    generic_ids={'text','source_text','source_body','source_content','source_card','source_passage',
                 'reading_text','reading_body','reading_content','reading_card',
                 'text_body','text_card','text_content'}
    references=[]
    def collect_references(node):
        """Count every original source reference before choosing an unused source."""
        if isinstance(node,str) or 'comment' in node:return
        slot=dict(node['attrs']).get('data-content','') or ''
        if slot.startswith('stimulus_'):references.append(source_id(slot))
        for child in node['children']:collect_references(child)
    for root in parser.root:collect_references(root)
    missing=[sid for sid in references if sid not in seen]
    unused=[sid for sid in seen if sid not in references]

    def letter_alias(node,sid):
        """Resolve Text A to the sole unused declared Card A, retaining its complete text."""
        match=re.fullmatch(r'(?:text|card|source|reading|passage)_([a-h])',sid)
        if not match or references.count(sid)!=1:return None
        if isinstance(captions,list) and any(isinstance(c,dict) and c.get('id')==sid for c in captions):return None
        pattern=r'(?:text|card|source|reading|passage)_'+match[1]
        candidates=[candidate for candidate in unused if re.fullmatch(pattern,candidate)]
        if len(candidates)!=1 or sum(bool(re.fullmatch(pattern,other)) for other in missing)!=1:return None
        pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in node['children']]
        if any(piece is None for piece in pieces):return None
        printed=' '.join(''.join(pieces).split())
        expected=' '.join(str(sources[candidates[0]].get('text','')).split())
        label=' '.join(str(sources[candidates[0]].get('label','')).split())
        copies={expected}
        if label:copies.update({label+' '+expected,label+': '+expected,label+'. '+expected})
        if not expected or printed and printed not in copies:return None
        return 'stimulus_'+candidates[0]

    def generic_alias(node,sid):
        """Rebind one generic placeholder to one complete, unused declared source."""
        if sid not in generic_ids or missing!=[sid] or len(unused)!=1:return None
        candidate=unused[0]
        pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in node['children']]
        if any(p is None for p in pieces):return None
        printed=' '.join(''.join(pieces).split())
        expected=' '.join(str(sources[candidate].get('text','')).split())
        if printed and printed!=expected:return None
        return 'stimulus_'+candidate


    def caption_group(node):
        """Unwrap a source-named layout group only when complete declared captions own it.

        No source is invented or removed. Real declared sources take precedence;
        empty unknown placeholders, partial wording, media, response surfaces and
        undeclared text remain errors for the existing source/content validators.
        """
        if not isinstance(captions,list):return None
        declared={'caption_'+c['id']:c['text'] for c in captions if isinstance(c,dict)
                  and isinstance(c.get('id'),str) and isinstance(c.get('text'),str)}
        by_text={}
        for slot,value in declared.items():by_text.setdefault(' '.join(value.split()).casefold(),[]).append(slot)
        tentative=deepcopy(node);used=[]

        def inspect(child):
            """Bind complete unique caption copies; preserve all grouping layout markup."""
            if isinstance(child,str):
                if not child.strip():return child
                matches=by_text.get(' '.join(child.split()).casefold(),[])
                if len(matches)!=1:raise ValueError('Independent group wording')
                used.append(matches[0])
                return {'tag':'span','attrs':[('data-content',matches[0])],'children':[]}
            if 'comment' in child or child['tag'] not in {'div','section','p','span','h2','h3','h4','ul','ol','li','table','tbody','tr','td','th','strong','b','em','br'}:
                raise ValueError('Independent group content')
            attrs=dict(child['attrs']);slot=attrs.get('data-content')
            if slot:
                from core.content_binding import canonical_content_slot
                slot=canonical_content_slot(slot,declared)
                if slot not in declared:raise ValueError('Unknown group member')
                pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in child['children']]
                if any(p is None for p in pieces):raise ValueError('Nontext caption content')
                printed=' '.join(''.join(pieces).split()).casefold()
                if printed and printed!=' '.join(declared[slot].split()).casefold():raise ValueError('Partial caption copy')
                child['attrs']=[(k,slot if k=='data-content' else v) for k,v in child['attrs']]
                used.append(slot)
                return child
            pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in child['children']]
            value=' '.join(''.join(pieces).split()).casefold() if all(p is not None for p in pieces) else ''
            matches=by_text.get(value,[])
            if value and len(matches)==1:
                child['attrs'].append(('data-content',matches[0]));used.append(matches[0]);child['children']=[]
                return child
            if re.search(r'(?:^|;)\s*(?:min-|max-)?height\s*:',attrs.get('style',''),re.I):
                raise ValueError('Independent group workspace')
            child['children']=[inspect(c) for c in child['children']]
            return child

        try:tentative['children']=[inspect(c) for c in tentative['children']]
        except ValueError:return None
        if len(used)<2 or len(used)!=len(set(used)):return None
        tentative['attrs']=[(k,v) for k,v in tentative['attrs'] if k!='data-content']
        return tentative

    def label_slot(node, sid):
        """Bind an explicit source-heading alias only to an already declared label.

        A real source whose ID ends in _label takes precedence. Never infer a
        missing label from the ID, discard prefilled wording, or swallow media.
        """
        if sid in seen or not sid.endswith('_label') or not isinstance(captions,list):
            return None
        label=sources.get(sid[:-6],{}).get('label')
        if not isinstance(label,str) or not label.strip() or len(label.strip())>120:
            return None
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,23}',sid):
            return None

        def wording(child):
            """Accept only plain text and harmless inline formatting in a label."""
            if isinstance(child,str):return child
            if child.get('tag') not in {'span','strong','b','em','br'} or any(
                    k.startswith('data-') for k,_ in child.get('attrs',[])):
                raise ValueError('Source label alias contains independent content')
            return ' ' if child['tag']=='br' else ''.join(wording(c) for c in child['children'])

        try:
            printed=' '.join(''.join(wording(c) for c in node['children']).split())
        except ValueError:
            return None
        if printed and printed!=' '.join(label.split()):return None
        existing=[c for c in captions if isinstance(c,dict) and c.get('id')==sid]
        if existing:
            if len(existing)!=1 or existing[0].get('text')!=label.strip():return None
        else:
            captions.append({'id':sid,'text':label.strip()})
        return 'caption_'+sid

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
                else:
                    heading=letter_alias(node,sid) or generic_alias(node,sid) or label_slot(node,sid)
                    if heading:
                        value=heading
                        changed=True
            attrs.append((key,value))
        node['attrs']=attrs
        for child in node['children']:
            visit(child)
        slot=dict(node['attrs']).get('data-content','') or ''
        if slot.startswith('stimulus_') and source_id(slot) not in seen:
            group=caption_group(node)
            if group is not None:
                node.update(group);changed=True

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
        if isinstance(captions,list):exercise['captions']=captions
        page['html']=''.join(render(node) for node in parser.root)


def stimulus_capacity(config: dict) -> int:
    """Return the explicitly configured short-source capacity with a bounded legacy default."""
    limit = config.get('stimulus_limit',4)
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError('Source stimulus limit must be between 1 and 8')
    return limit


def merge_missing_sources(original: dict, correction: dict) -> dict:
    """Adopt missing supporting sources without rewriting authored tasks or computed puzzles."""
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
            sid=cid
            collision=cid in ids
            if collision:
                # Captions and sources are separate namespaces. A reused ID is
                # not permission to overwrite or merge two different excerpts.
                reserved=ids|{c.get('id') for c in captions if isinstance(c,dict)}
                for number in range(1,len(reserved)+2):
                    suffix=f'_context_{number}'
                    candidate=cid[:24-len(suffix)]+suffix
                    if candidate not in reserved:
                        sid=candidate;break
            migrated=dict(caption,id=sid);stimuli.append(migrated)
            ids.add(sid)
            # On a collision, only the explicit caption namespace belongs to
            # the migrated paragraph. The existing source reference stays put.
            prefix='caption_' if collision else '(?:caption_)?'
            pattern = r'(\bdata-content\s*=\s*)([\'\"])'+prefix+re.escape(cid)+r'\2'
            page['html'] = re.sub(pattern,lambda m:m[1]+m[2]+'stimulus_'+sid+m[2],page['html'])
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
