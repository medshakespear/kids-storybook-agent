"""Lossless normalization of factual context and empty slots on computed puzzles."""
import html
import re
from core.content_binding import CanonicalTextContainers, CONTAINERS, validate_caption_budget
from core.context_recovery import contextual_text


def normalize_exact_context(exercise: dict, markup: str, *, context_limit: int = 6) -> str:
    """Split complete long factual captions and omit only empty unused text slots.

    The computed diagram owns directions. Independent instructions, media and
    writing panels are never removed or relabeled by this normalization.
    """
    if exercise.get('render_mode') != 'exact':
        return markup
    captions = exercise.get('captions', [])
    if not isinstance(captions, list):
        return markup
    parser = CanonicalTextContainers({})
    parser.feed(markup); parser.close()
    if parser.stack:
        return markup
    omitted = set()
    nodes = []

    def visit(node):
        """Collect explicit text slots without interpreting arbitrary layout wording."""
        if isinstance(node, str) or 'comment' in node:
            return
        nodes.append(node)
        slot = dict(node['attrs']).get('data-content')
        if (node['tag'] in CONTAINERS and slot in {'directions', 'passage'} and not exercise.get(slot)
                and not any(k not in {'style','data-content'} for k,_ in node['attrs'])):
            # Only an actually empty placeholder without a sized work area.
            style = dict(node['attrs']).get('style', '')
            sized = re.search(r'(?:^|;)\s*(?:height|min-height|max-height|border(?:-[a-z]+)?)\s*:', style, re.I)
            if all(isinstance(c, str) and not c.strip() for c in node['children']):
                if sized:
                    # An empty box can still be student workspace. Detach the
                    # nonexistent text binding while retaining its full geometry.
                    node['attrs'] = [(k,v) for k,v in node['attrs'] if k != 'data-content']
                else:
                    omitted.add(id(node))
            elif not sized:
                pieces = [parser.plain_text(c) for c in node['children']]
                text = ' '.join(''.join(pieces).split()).casefold() if all(p is not None for p in pieces) else ''
                matches = [c['id'] for c in captions if isinstance(c,dict) and isinstance(c.get('id'),str)
                           and isinstance(c.get('text'),str) and text and text == ' '.join(c['text'].split()).casefold()]
                if len(matches) == 1:
                    node['attrs'] = [(k,'caption_'+matches[0] if k == 'data-content' else v) for k,v in node['attrs']]
        for child in node['children']:
            visit(child)

    for node in parser.root:
        visit(node)
    updated = list(captions)
    for caption in captions:
        if not isinstance(caption, dict):
            continue
        cid, text = caption.get('id'), caption.get('text')
        if (not isinstance(cid, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,23}', cid)
                or not isinstance(text, str) or not 120 < len(text.strip()) <= 480
                or not contextual_text(text)):
            continue
        matches = [n for n in nodes if dict(n['attrs']).get('data-content') in {cid, 'caption_' + cid}]
        if len(matches) != 1 or sum(isinstance(c,dict) and c.get('id') == cid for c in captions) != 1:
            continue
        node = matches[0]
        if node['tag'] not in CONTAINERS or any(k not in {'style','data-content'} for k,_ in node['attrs']):
            continue
        pieces = [parser.plain_text(child) for child in node['children']]
        if any(p is None for p in pieces):
            continue
        printed = ' '.join(''.join(pieces).split())
        if printed and printed.casefold() != ' '.join(text.split()).casefold():
            continue
        chunks, remaining = [], text.strip()
        while len(remaining) > 120:
            cut = remaining.rfind(' ', 0, 121)
            if cut < 1:
                break
            chunks.append(remaining[:cut]); remaining = remaining[cut + 1:]
        if len(remaining) > 120:
            continue
        chunks.append(remaining)
        ids = {c.get('id') for c in updated if isinstance(c,dict)}
        replacements = [{'id':cid[:15] + f'_part{i}', 'text':chunk} for i,chunk in enumerate(chunks, 1)]
        if any(c['id'] in ids for c in replacements):
            continue
        proposed = []
        for old in updated:
            proposed.extend(replacements if old is caption else [old])
        try:
            validate_caption_budget(proposed,context_limit=context_limit)
        except ValueError:
            continue
        updated = proposed
        node['attrs'] = [(k,v) for k,v in node['attrs'] if k != 'data-content']
        node['children'] = []
        for part in replacements:
            if node['children']:
                node['children'].append(' ')
            node['children'].append({'tag':'span', 'attrs':[('data-content','caption_' + part['id'])], 'children':[]})
    if 'captions' in exercise or updated != captions:
        exercise['captions'] = updated

    def render(node):
        """Serialize literal retained layout; never infer or replace other bindings."""
        if id(node) in omitted:
            return ''
        if isinstance(node, str):
            return html.escape(node, quote=False)
        if 'comment' in node:
            return '<!--' + node['comment'] + '-->'
        attrs = ' '.join(f'{k}="{html.escape(v or "", quote=True)}"' for k,v in node['attrs'])
        start = f'<{node["tag"]} {attrs}>'
        return start if node['tag'] in {'img','br'} else start + ''.join(render(c) for c in node['children']) + f'</{node["tag"]}>'

    return ''.join(render(node) for node in parser.root)
