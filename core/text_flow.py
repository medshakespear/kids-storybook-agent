"""Let mixed-mode text grow in normal flow without resizing artwork or answer boxes."""
import re
import html

from core.content_binding import CanonicalTextContainers


def reflow_text_heights(markup: str) -> str:
    """Remove height clamps from text and redundant wrappers, retaining usable workspace."""
    parser = CanonicalTextContainers({})
    parser.feed(markup)
    parser.close()
    if parser.stack:
        return markup
    changed = False

    def visit(node):
        """Track printed text and protected dimensions without modifying media or response spans."""
        nonlocal changed
        if isinstance(node,str):
            return bool(re.search(r'\w',node.replace('_',''))), False
        if 'comment' in node:
            return False, False
        children = [visit(child) for child in node['children']]
        style = dict(node['attrs']).get('style','') or ''
        text = any(ink for ink,_ in children)
        protected = (node['tag']=='img' or
                     (node['tag']=='span' and re.search(r'border\s*:\s*0\.4mm\s+solid\s+#809aa6',style,re.I) is not None))
        child_space = any(space for _,space in children)
        # Empty / underscore-only dimensioned panels are student work surfaces.
        if not text and re.search(r'(?:^|;)\s*(?:height|min-height)\s*:',style,re.I):
            protected = True
        if not protected and text and node['tag'] in {'p','div','section','td','th','span','h1','h2','h3','h4','h5','h6','table','tr'}:
            names = {'height','min-height','max-height'}
            declarations = [part for part in style.split(';')
                            if part.split(':',1)[0].strip().lower() not in names]
            cleaned = ';'.join(declarations)
            if cleaned != style:
                node['attrs'] = [(key,cleaned if key=='style' else value) for key,value in node['attrs']]
                changed = True
        return text, protected or child_space

    for node in parser.root:
        visit(node)

    def render(node):
        """Serialize literally, without inferring new content slots after text binding."""
        if isinstance(node,str):
            return html.escape(node,quote=False)
        if 'comment' in node:
            return '<!--'+node['comment']+'-->'
        attrs=' '.join(f'{key}="{html.escape(value or "",quote=True)}"' for key,value in node['attrs'])
        start=f'<{node["tag"]} {attrs}>'
        if node['tag'] in {'img','br'}:
            return start
        return start+''.join(render(child) for child in node['children'])+f'</{node["tag"]}>'

    return ''.join(render(node) for node in parser.root) if changed else markup
