"""Translate simple equal-column CSS grids into measured printable tables."""
import html
import re
import tinycss2
from core.content_binding import CanonicalTextContainers


def literal_html(node) -> str:
    """Serialize retained markup without inferring content slots or discarding work areas."""
    if isinstance(node,str): return html.escape(node,quote=False)
    if 'comment' in node: return '<!--'+node['comment']+'-->'
    attrs=' '.join(f'{k}="{html.escape(v or "",quote=True)}"' for k,v in node['attrs'])
    start=f'<{node["tag"]} {attrs}>'
    return start if node['tag'] in {'img','br'} else start+''.join(literal_html(c) for c in node['children'])+f'</{node["tag"]}>'


def equal_columns(value: str) -> int | None:
    """Accept only one to four equal fractional tracks, never named or positioned areas."""
    value=re.sub(r'\s+',' ',value.strip().lower())
    repeated=re.fullmatch(r'repeat\(\s*([1-4])\s*,\s*(?:1fr|minmax\(\s*0\s*,\s*1fr\s*\))\s*\)',value)
    if repeated: return int(repeated[1])
    tracks=value.split()
    if 1 <= len(tracks) <= 4 and all(track=='1fr' for track in tracks): return len(tracks)
    return None


def normalize_print_grid(markup: str) -> str:
    """Preserve ordered cells while translating a simple inline grid to a fixed table."""
    if not re.search(r'grid-template-columns|display\s*:\s*(?:inline-)?grid',markup,re.I): return markup
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack: raise ValueError('Exercise layout tags must be balanced')
    changed=False

    def visit(node):
        """Transform only explicit equal-track grids; leave unsupported CSS for validation."""
        nonlocal changed
        if isinstance(node,str) or 'comment' in node: return
        for child in node['children']: visit(child)
        attrs=dict(node['attrs']);style=attrs.get('style','') or ''
        if len(attrs)!=len(node['attrs']): raise ValueError('Duplicate layout attributes')
        declarations=tinycss2.parse_declaration_list(style,skip_comments=True,skip_whitespace=True)
        if any(d.type!='declaration' for d in declarations): return
        values={d.lower_name:tinycss2.serialize(d.value).strip() for d in declarations}
        grid=values.get('display','').lower() in {'grid','inline-grid'}
        if not grid and 'grid-template-columns' not in values: return
        columns=equal_columns(values.get('grid-template-columns',''))
        unsupported={k for k in values if k.startswith('grid-') and k!='grid-template-columns'}
        if not grid or columns is None or unsupported or attrs.get('data-content'):
            raise ValueError('Use a simple 1-4 equal-column grid or a normal print table; complex grid placement needs an explicit layout repair')
        cells=[c for c in node['children'] if not isinstance(c,str) or c.strip()]
        if not cells or any(isinstance(c,str) or 'comment' in c for c in cells):
            raise ValueError('Printable grid cells must be separate content containers')
        gap=values.get('gap','0mm').split()
        if len(gap) not in {1,2}: raise ValueError('Printable grid gap must use positive mm dimensions')
        row=values.get('row-gap',gap[0]);col=values.get('column-gap',gap[-1])
        if not all(re.fullmatch(r'(?:0|\d+(?:\.\d+)?mm)',v) for v in (row,col)):
            raise ValueError('Printable grid gap must use positive mm dimensions')
        kept=[d for d in declarations if d.lower_name not in {'display','grid-template-columns','gap','row-gap','column-gap'}]
        attrs['style']=tinycss2.serialize(kept)+';display:block'
        node['attrs']=list(attrs.items())
        rows=[]
        for offset in range(0,len(cells),columns):
            group=cells[offset:offset+columns]
            group=group+[None]*(columns-len(group))
            rows.append({'tag':'tr','attrs':[],'children':[
                {'tag':'td','attrs':[('style','vertical-align:top;padding:0')],
                 'children':[] if c is None else [c]} for c in group]})
        node['children']=[{'tag':'table','attrs':[('style',
            f'width:100%;table-layout:fixed;border-spacing:{col} {row}')],
            'children':[{'tag':'tbody','attrs':[],'children':rows}]}]
        changed=True

    for node in parser.root: visit(node)
    return ''.join(literal_html(n) for n in parser.root) if changed else markup
