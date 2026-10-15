"""Recover declared labels at unambiguous metadata or illustration anchors."""
import re
from core.content_binding import CanonicalTextContainers, canonical_content_slot
from core.print_grid import literal_html


def restore_declared_labels(markup: str, blocks: dict, exercise: dict, config: dict) -> str:
    """Restore retained captions without inventing wording or guessing diagram associations."""
    if not config.get('student_workbook') or exercise.get('render_mode') != 'authored':
        return markup
    parser = CanonicalTextContainers(blocks)
    parser.feed(markup)
    parser.close()
    used = set()
    assets = []
    containers = []
    metadata = {}

    def visit(children, inside=False, parent_tag=None):
        """Record only anchors outside canonical text slots."""
        for node in children:
            if isinstance(node, str) or 'comment' in node:
                continue
            attrs = dict(node['attrs'])
            slot = canonical_content_slot(attrs.get('data-content'), blocks)
            if slot:
                used.add(slot)
                if slot in {'name','date'} and not inside:
                    metadata.setdefault(slot, []).append(node)
            if not inside and not slot:
                if node['tag'] == 'img' and attrs.get('data-asset') and parent_tag in {None,'div','section','td','li'}:
                    assets.append((children, node, attrs['data-asset']))
                pieces = [parser.plain_text(c) for c in node['children']]
                if all(p is not None for p in pieces):
                    containers.append((node, ' '.join(''.join(pieces).split()).casefold()))
            visit(node['children'], inside or bool(slot), node['tag'])

    visit(parser.root)
    for caption in exercise.get('captions', []):
        slot = 'caption_' + caption['id']
        if slot in used or slot not in blocks:
            continue
        text = ' '.join(caption['text'].split()).casefold()
        # A complete printed label is stronger evidence than its generated ID.
        matches = [node for node, value in containers if value and value == text]
        if len(matches) == 1:
            matches[0]['attrs'].append(('data-content', slot))
            matches[0]['children'] = []
            used.add(slot)
            continue
        cid = caption['id']
        anchor = None
        if cid in {'date_label', 'event_label', 'name_label'} and re.fullmatch(
                r'(?:date|event|name)\s*:\s*[_\s]*', text):
            # Reuse a blank built-in field instead of printing Date/Name twice.
            field = cid.removesuffix('_label')
            if len(metadata.get(field, [])) == 1:
                node = metadata[field][0]
                pieces = [parser.plain_text(c) for c in node['children']]
                own = ''.join(p for p in pieces if p is not None).strip()
                if all(p is not None for p in pieces) and (not own or re.fullmatch(
                        field + r'\s*:\s*[_\s]*', own, re.I)):
                    node['attrs'] = [(k, slot if k == 'data-content' else v) for k,v in node['attrs']]
                    node['children'] = []
                    used.add(slot)
                    continue
            # Identification labels have no inferred factual value.
            anchor = (parser.root, 0)
        elif cid.endswith('_label'):
            subject = cid[:-6]
            candidates = [(children, node) for children, node, asset in assets
                          if subject and subject in re.split(r'[_-]', asset)]
            if len(candidates) == 1:
                children, node = candidates[0]
                anchor = (children, children.index(node) + 1)
        if anchor is not None:
            children, index = anchor
            children.insert(index, {'tag': 'p', 'attrs': [('data-content', slot),
                ('style', f"font-size:{config.get('minimum_text_pt',12)}pt;line-height:1.2;margin:0 0 2mm")], 'children': []})
            used.add(slot)
    return ''.join(literal_html(node) for node in parser.root)
