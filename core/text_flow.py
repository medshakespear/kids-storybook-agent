"""Let mixed-mode text grow in normal flow without resizing artwork or answer boxes."""
import re
import html

from core.content_binding import CanonicalTextContainers


def reflow_text_heights(markup: str, *, stack_rows: bool = False) -> str:
    """Remove text clamps; optionally stack cramped flex rows for measured recovery."""
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
        # Retained source layouts contain empty canonical slots whose actual
        # wording is supplied by the compiler. Those are text, not blank panels.
        text = any(ink for ink,_ in children) or bool(dict(node['attrs']).get('data-content'))
        protected = (node['tag']=='img' or
                     (node['tag']=='span' and re.search(r'border\s*:\s*0\.4mm\s+solid\s+#809aa6',style,re.I) is not None))
        child_space = any(space for _,space in children)
        declarations = {part.split(':',1)[0].strip().lower():part.split(':',1)[1].strip().lower()
                        for part in style.split(';') if ':' in part}
        vertical = declarations.get('flex-direction')=='column'
        row = declarations.get('flex-direction','row')=='row'
        if (text and node['tag'] in {'div','section','p','span'}
                and declarations.get('display') in {'flex','inline-flex'}
                and (vertical or (stack_rows and row))):
            # Preserve DOM order and every child. Explicit reverse/wrap layouts
            # are not guessed. The recovery caller must still measure page fit.
            if declarations.get('flex-wrap','nowrap')=='nowrap':
                removed={'display','flex-direction','align-items','justify-content'}
                style=';'.join(part for part in style.split(';')
                              if part.split(':',1)[0].strip().lower() not in removed)+';display:block'
                node['attrs']=[(key,style if key=='style' else value) for key,value in node['attrs']]
                changed=True
                if row:
                    for child,(ink,_) in zip(node['children'],children):
                        if not isinstance(child,dict) or not ink or child.get('tag')=='img':
                            continue  # Keep blank work surfaces and media dimensions.
                        names={'width','min-width','max-width','flex-basis','flex-grow','flex-shrink'}
                        child['attrs']=[(key,';'.join(part for part in (value or '').split(';')
                            if part.split(':',1)[0].strip().lower() not in names) if key=='style' else value)
                            for key,value in child['attrs']]
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
