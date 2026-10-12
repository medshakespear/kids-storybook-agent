"""Retain short authored table data as canonical captions without inventing content."""
import re

from core.content_binding import CanonicalTextContainers

TABLE_CAPTION_LIMIT = 36


def prepare_table_captions(page: dict) -> set[str]:
    """Bind literal table cells and resolve only unambiguous declared caption aliases.

    Empty unknown slots remain errors. No value is inferred from a question, answer,
    image prompt or discarded model attempt. Actions remain exercise questions.
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
