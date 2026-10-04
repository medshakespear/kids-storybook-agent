"""Remove only captions proven to repeat the computed graphic's instructions."""
import html
import re
from core.content_binding import CanonicalTextContainers
from core.task_visuals import build_visual


def remove_duplicate_instruction_captions(exercise: dict, markup: str) -> str:
    """Keep additional actions; omit literal instruction repeats without deleting workspaces."""
    captions = exercise.get('captions')
    if not isinstance(captions,list) or not isinstance(exercise.get('visual'),dict):
        return markup
    svg,_ = build_visual(exercise['visual'])
    labels = [html.unescape(value) for value in re.findall(r'<text\b[^>]*>(.*?)</text>',svg)][:2]

    def normalized(value):
        """Ignore only optional politeness, numbering, case and terminal punctuation."""
        value = ' '.join(value.split()).casefold()
        value = re.sub(r'^\d+\.\s*','',value)
        return re.sub(r'^please\s+','',value).rstrip('.! ')

    instructions = {normalized(value) for value in labels}
    instructions.add(normalized(' '.join(labels)))
    parser = CanonicalTextContainers({})
    parser.feed(markup); parser.close()
    if parser.stack:
        return markup
    removed, omitted = set(), set()

    def safe(node, root=False):
        """Never remove graphics, nested bindings or explicitly sized response panels."""
        if isinstance(node,str):
            return node
        if 'comment' in node or node['tag'] not in {'p','div','section','span','strong','b','em','br'}:
            return None
        if not root and node['tag'] in {'p','div','section'}:
            return None
        attrs = dict(node['attrs'])
        if not root and any(key.startswith('data-') for key in attrs):
            return None
        if any(key.startswith('data-') and key!='data-content' for key in attrs):
            return None
        if re.search(r'(?:^|;)\s*(?:height|min-height|max-height)\s*:',attrs.get('style',''),re.I):
            return None
        values = [safe(child) for child in node['children']]
        return None if any(value is None for value in values) else ''.join(values)

    def locate(node, slot, matches):
        """Find explicit caption slots without inferring independent task text."""
        if isinstance(node,str) or 'comment' in node:
            return
        if dict(node['attrs']).get('data-content')==slot:
            matches.append(node)
        for child in node['children']:
            locate(child,slot,matches)

    for caption in captions:
        if not isinstance(caption,dict) or not isinstance(caption.get('text'),str) or not isinstance(caption.get('id'),str):
            continue
        if sum(isinstance(c,dict) and c.get('id')==caption['id'] for c in captions)!=1:
            continue
        if normalized(caption['text']) not in instructions:
            continue
        matches = []
        for node in parser.root:
            locate(node,'caption_'+caption['id'],matches)
        if len(matches)!=1:
            continue
        value = safe(matches[0],True)
        if value is None or (value.strip() and normalized(value)!=normalized(caption['text'])):
            continue
        removed.add(caption['id']); omitted.add(id(matches[0]))
    if not removed:
        return markup

    def render(node):
        """Retain all other text, attributes, assets and work areas."""
        if id(node) in omitted:
            return ''
        if isinstance(node,str):
            return html.escape(node,quote=False)
        if 'comment' in node:
            return '<!--'+node['comment']+'-->'
        attrs = ' '.join(f'{key}="{html.escape(value or "",quote=True)}"' for key,value in node['attrs'])
        start = f'<{node["tag"]} {attrs}>'
        return start if node['tag'] in {'img','br'} else start+''.join(render(child) for child in node['children'])+f'</{node["tag"]}>'

    exercise['captions'] = [caption for caption in captions if not isinstance(caption,dict) or caption.get('id') not in removed]
    return ''.join(render(node) for node in parser.root)
