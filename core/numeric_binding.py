"""Register standalone printed integers without guessing whether they are labels or data."""
import html
import re

from core.content_binding import CanonicalTextContainers,caption_budget_available,canonical_content_slot
from core.print_grid import literal_html


def bind_numeric_text(markup: str, exercise: dict, blocks: dict, *, context_limit: int, table_ids: set) -> str:
    """Bind each whole numeric text node in place, retaining repeated values independently.

    Existing content slots remain untouched. Never combine adjacent numeric nodes,
    infer a calculation, discard a value as decoration, change a question/key or
    consume a blank working panel. Full content and print checks still follow.
    """
    captions=exercise.get('captions',[])
    if not isinstance(captions,list): return markup
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack: return markup
    used=set();changed=False

    def collect(node):
        """Reserve every actual caption reference before reusing an otherwise missing slot."""
        if isinstance(node,str) or 'comment' in node: return
        slot=canonical_content_slot(dict(node['attrs']).get('data-content'),blocks)
        if slot: used.add(slot)
        for child in node['children']: collect(child)

    for node in parser.root: collect(node)

    def bind(value):
        """Return one canonical numeric slot while preserving its complete printed token."""
        nonlocal changed
        text=value.strip()
        if not re.fullmatch(r'(?:[-−]?\d{1,6}|[1-9]\d?[.)])',text): return None
        existing=[caption for caption in captions if isinstance(caption,dict)
            and caption.get('text')==text and 'caption_'+caption.get('id','') not in used]
        if len(existing)==1:
            slot='caption_'+existing[0]['id']
        else:
            if not caption_budget_available(captions,text,context_limit=context_limit,table_ids=table_ids):
                return None  # The normal validator/repair still handles a genuinely full manifest.
            ids={caption.get('id') for caption in captions if isinstance(caption,dict)}
            cid=next(f'printed_number_{n}' for n in range(1,len(ids)+2) if f'printed_number_{n}' not in ids)
            captions.append({'id':cid,'text':text});slot='caption_'+cid
            blocks[slot]=html.escape(text)
        used.add(slot);changed=True
        return slot

    def visit(node):
        """Keep all layout nodes; replace only a whole integer outside bound content."""
        if isinstance(node,str):
            slot=bind(node)
            if slot is None: return node
            leading=node[:len(node)-len(node.lstrip())];trailing=node[len(node.rstrip()):]
            return [leading,{'tag':'span','attrs':[('data-content',slot)],'children':[]},trailing]
        if 'comment' in node or any(k=='data-content' for k,_ in node['attrs']): return node
        # Preserve a number-only leaf's own color, dimensions and badge shape.
        if len(node['children'])==1 and isinstance(node['children'][0],str):
            text=node['children'][0]
            title=re.sub(r'<[^>]*>','',html.unescape(blocks.get('title',''))).strip()
            if node['tag'] in {'h1','h2','h3','h4','h5','h6'} and text.strip()==title:
                return node
            slot=bind(text) if text==text.strip() else None
            if slot:
                node['attrs'].append(('data-content',slot));node['children']=[]
                return node
        children=[]
        for child in node['children']:
            result=visit(child)
            children.extend(result if isinstance(result,list) else [result])
        node['children']=children
        return node

    root=[]
    for node in parser.root:
        result=visit(node);root.extend(result if isinstance(result,list) else [result])
    if not changed: return markup
    exercise['captions']=captions
    return ''.join(literal_html(node) for node in root)
