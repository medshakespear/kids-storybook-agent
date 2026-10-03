"""Bind complete declarative context without turning student actions into decoration."""
import html
import re
from core.content_binding import CanonicalTextContainers


def contextual_text(value: str) -> bool:
    """Accept clearly declarative context; leave questions, solutions and commands for repair."""
    if '?' in value or re.search(r'\b(?:answer|solution|correct choice)\b',value,re.I):
        return False
    if re.search(r'(?:^|[.!?]\s+)(?:please\s+|now\s+|then\s+)?(?:draw|write|count|sort|match|circle|find|trace|explain|describe|calculate|solve|choose|complete|help|design|create|compare)\b',value,re.I):
        return False
    return bool(re.search(r'\b(?:is|are|was|were|use|uses|include|includes|have|has|tells|tell|helps|help|can|often)\b',value,re.I))


def bind_contextual_wording(page: dict, title: str = '') -> None:
    """Promote only complete unbound factual containers, retaining every word and all tasks."""
    exercise = page.get('exercise')
    if not isinstance(exercise,dict) or exercise.get('render_mode')!='exact':
        return
    captions = exercise.get('captions', [])
    if not isinstance(captions,list):
        return
    parser = CanonicalTextContainers({})
    parser.feed(page['html']); parser.close()
    if parser.stack:
        return
    known = [str(c.get('text','')) for c in captions if isinstance(c,dict)]
    known += [title]
    known += [str(exercise.get(k,'')) for k in ('directions','passage')]
    known += [str(q.get('prompt','')) for q in exercise.get('questions',[]) if isinstance(q,dict)]
    normalize = lambda text: ' '.join(text.split()).casefold()
    known = {normalize(v) for v in known if v}
    changed = False

    def plain(node, root=False):
        """Extract inline text only; retain media, nested slots and workspaces untouched."""
        if isinstance(node,str):
            return node
        if not root and node.get('tag') in {'p','div','section'}:
            return None
        if 'comment' in node or node['tag'] not in {'p','div','section','span','b','strong','em','br'}:
            return None
        if any(key.startswith('data-') for key,_ in node['attrs']):
            return None
        if re.search(r'(?:^|;)\s*(?:height|min-height|max-height)\s*:',dict(node['attrs']).get('style',''),re.I):
            return None
        if node['tag']=='br':
            return ' '
        values = [plain(child) for child in node['children']]
        return None if any(v is None for v in values) else ''.join(values)

    def visit(node, in_slot=False):
        """Bind a whole context paragraph instead of inferring isolated word fragments."""
        nonlocal changed
        if isinstance(node,str) or 'comment' in node:
            return
        in_slot = in_slot or bool(dict(node['attrs']).get('data-content'))
        text = None if in_slot or node['tag'] not in {'p','div','section'} else plain(node, True)
        value = ' '.join(text.split()) if text is not None else ''
        if value and normalize(value) not in known and contextual_text(value):
            chunks, remaining = [], value
            while len(remaining)>120:
                cut = remaining.rfind(' ',0,121)
                if cut<1:
                    return
                chunks.append(remaining[:cut]); remaining=remaining[cut+1:]
            if remaining:
                chunks.append(remaining)
            if len(captions)+len(chunks)>6 or any(not contextual_text(c) and re.match(r'^(?:count|sort|match|draw|write|circle|find|trace|solve)\b',c,re.I) for c in chunks):
                return
            ids = {c.get('id') for c in captions if isinstance(c,dict)}
            children = []
            for chunk in chunks:
                index = next(n for n in range(1,20) if f'context_auto_{n}' not in ids)
                cid=f'context_auto_{index}'; ids.add(cid)
                captions.append({'id':cid,'text':chunk})
                if children:
                    children.append(' ')
                children.append({'tag':'span','attrs':[('data-content','caption_'+cid)],'children':[]})
            node['children']=children
            known.add(normalize(value));changed=True
            return
        for child in node['children']:
            visit(child,in_slot)

    def render(node):
        """Serialize the retained tree without dropping unrelated content or dimensions."""
        if isinstance(node,str):
            return html.escape(node,quote=False)
        if 'comment' in node:
            return '<!--'+node['comment']+'-->'
        attrs=' '.join(f'{key}="{html.escape(value or "",quote=True)}"' for key,value in node['attrs'])
        start=f'<{node["tag"]} {attrs}>'
        return start if node['tag'] in {'img','br'} else start+''.join(render(c) for c in node['children'])+f'</{node["tag"]}>'
    for node in parser.root:
        visit(node)
    if changed:
        exercise['captions']=captions
        page['html']=''.join(render(n) for n in parser.root)
