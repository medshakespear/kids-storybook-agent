"""Retain short authored table data as canonical captions without inventing content."""
import re

from core.content_binding import CanonicalTextContainers

TABLE_CAPTION_LIMIT = 36
NEUTRAL_HEADERS = {
    'feature':'Feature', 'characteristic':'Characteristic', 'category':'Category',
    'criterion':'Criterion', 'item':'Item', 'detail':'Detail', 'description':'Description',
    'source':'Source', 'evidence':'Evidence', 'observation':'Observation', 'notes':'Notes',
    'comparison':'Comparison', 'similarities':'Similarities', 'differences':'Differences',
    'symbolic':'Symbolic',
}


def neutral_table_header(text: str) -> bool:
    """Accept only organizational headings, never facts, task instructions or solutions."""
    return isinstance(text,str) and ' '.join(text.split()).casefold() in NEUTRAL_HEADERS


def empty_table_header_slots(page: dict, *, allow_neutral_text: bool = False) -> set[str]:
    """Locate missing header labels; repaired cells may repeat a neutral heading.

    The default requires an empty original header. The optional repair check also
    accepts complete neutral wording, including inline formatting, but no media,
    nested content slots, instructions or source facts.
    """
    exercise=page.get('exercise')
    if not isinstance(exercise,dict) or exercise.get('render_mode')!='authored': return set()
    parser=CanonicalTextContainers({});parser.feed(page.get('html',''));parser.close()
    if parser.stack: return set()
    captions=exercise.get('captions',[])
    declared={c.get('id') for c in (captions if isinstance(captions,list) else [])
              if isinstance(c,dict)}
    known_slots={slot for cid in declared if isinstance(cid,str) for slot in (cid,'caption_'+cid)}
    found=set()

    def visit(node, in_table=False):
        """Do not authorize labels in data cells, ordinary headings or nonempty cells."""
        if isinstance(node,str) or 'comment' in node: return
        in_table=in_table or node['tag']=='table'
        slot=dict(node['attrs']).get('data-content')
        if in_table and node['tag']=='th' and isinstance(slot,str) and slot.startswith('caption_') and slot not in known_slots:
            cid=slot.removeprefix('caption_')
            pieces=[parser.plain_text(child) for child in node['children']]
            empty=all(isinstance(child,str) and not child.strip() for child in node['children'])
            neutral=(allow_neutral_text and all(p is not None for p in pieces)
                     and neutral_table_header(''.join(pieces)))
            if (re.fullmatch(r'[a-z][a-z0-9_]{0,23}',cid) and cid not in declared
                    and (empty or neutral)):
                found.add(cid)
        for child in node['children']: visit(child,in_table)

    for node in parser.root: visit(node)
    return found


def prepare_table_captions(page: dict) -> set[str]:
    """Bind literal table cells and resolve only unambiguous declared caption aliases.

    Empty data cells remain errors. An explicit empty header such as th_feature
    may receive its allowlisted organizational label. No factual value is inferred
    from a question, answer, image prompt or discarded model attempt.
    """
    exercise = page.get('exercise', {})
    captions = exercise.get('captions', [])
    if not isinstance(captions, list):
        return set()
    by_id = {c.get('id'): c for c in captions if isinstance(c, dict)}
    parser = CanonicalTextContainers({})
    parser.feed(page['html'])
    parser.close()
    if parser.stack:
        raise ValueError('Exercise layout tags must be balanced')
    table_ids, changed = set(), False
    missing_headers=empty_table_header_slots(page)

    def declared(slot):
        """Resolve IDs with zero or one caption prefix without guessing a field."""
        if not isinstance(slot, str):
            return None
        matches = [cid for cid in by_id if slot in {cid, 'caption_'+cid}]
        return matches[0] if len(matches) == 1 else None

    def visit(node, in_table=False, in_cell=False, in_slot=False):
        """Promote whole short literal cells, retaining surrounding design markup."""
        nonlocal changed
        if isinstance(node, str) or 'comment' in node:
            return
        attrs = dict(node['attrs'])
        in_table = in_table or node['tag'] == 'table'
        in_cell = in_table and (in_cell or node['tag'] in {'td', 'th'})
        slot = attrs.get('data-content')
        cid = declared(slot) if in_cell and not in_slot else None
        requested=slot.removeprefix('caption_') if isinstance(slot,str) else ''
        if cid is None and not in_slot and requested in missing_headers:
            key=re.sub(r'^(?:th|header|column|col)_','',requested)
            heading=NEUTRAL_HEADERS.get(key)
            if heading:
                cid=requested
                caption={'id':cid,'text':heading}
                captions.append(caption);by_id[cid]=caption
                changed=True
        if cid is not None:
            if cid in table_ids and all(parser.plain_text(child) is not None for child in node['children']):
                # The same header may legitimately appear in two tables. Clone
                # its already-declared text, never new content or a task value.
                replacement = next(f'table_cell_{n}' for n in range(1,100) if f'table_cell_{n}' not in by_id)
                caption = dict(by_id[cid], id=replacement)
                captions.append(caption)
                by_id[replacement] = caption
                cid = replacement
                node['attrs'] = [(key,val) for key,val in node['attrs'] if key != 'data-content']
                node['attrs'].append(('data-content','caption_'+cid))
                changed = True
            table_ids.add(cid)
            if len(table_ids) > TABLE_CAPTION_LIMIT:
                raise ValueError('Use at most 36 short table headers/data cells per activity; simplify the table')
        # Bind only a text-only complete table cell. Nested data slots and media
        # make plain_text return None, preserving the existing content ownership.
        if in_table and node['tag'] in {'td', 'th'} and not in_slot and cid is None:
            pieces = [parser.plain_text(child) for child in node['children']]
            value = ' '.join(''.join(pieces).split()) if all(p is not None for p in pieces) else ''
            caption_slot = slot is None or slot.startswith('caption_')
            command = re.search(r'^(?:please\s+)?(?:write|draw|count|sort|match|find|explain|calculate|solve|choose|complete|compare|design|create)\b', value, re.I)
            if (value and len(value) <= 120 and caption_slot and not command and '?' not in value
                    and not re.search(r'\b(?:answer|solution|correct choice)\b',value,re.I)):
                if len(table_ids) >= TABLE_CAPTION_LIMIT:
                    raise ValueError('Use at most 36 short table headers/data cells per activity; simplify the table')
                requested = slot.removeprefix('caption_') if slot else ''
                if requested and re.fullmatch(r'[a-z][a-z0-9_]{0,23}',requested) and requested not in by_id:
                    cid = requested
                else:
                    cid = next(f'table_cell_{n}' for n in range(1,100) if f'table_cell_{n}' not in by_id)
                caption = {'id':cid, 'text':value}
                captions.append(caption)
                by_id[cid] = caption
                table_ids.add(cid)
                node['attrs'] = [(key,val) for key,val in node['attrs'] if key != 'data-content']
                node['attrs'].append(('data-content','caption_'+cid))
                node['children'] = []
                changed = True
                return
        if slot is not None:
            in_slot = True
        for child in node['children']:
            visit(child,in_table,in_cell,in_slot)

    for node in parser.root:
        visit(node)
    if changed:
        exercise['captions'] = captions
        page['html'] = ''.join(parser.render(node) for node in parser.root)
    return table_ids
