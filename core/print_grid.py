"""Translate bounded inline CSS grids into measured printable tables."""
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


def print_gap(value: str) -> str:
    """Convert nonnegative absolute CSS lengths to physical print millimeters."""
    if value=='0':return '0mm'
    match=re.fullmatch(r'(\d+(?:\.\d+)?|\.\d+)(mm|px|pt|cm|in|pc)',value.lower())
    if not match:raise ValueError('Printable grid gap needs a nonnegative absolute length (mm, px, pt, cm, in or pc)')
    factor={'mm':1,'px':25.4/96,'pt':25.4/72,'cm':10,'in':25.4,'pc':25.4/6}[match[2]]
    return f'{float(match[1])*factor:.6f}'.rstrip('0').rstrip('.')+'mm'


def normalize_print_grid(markup: str, *, allow_weighted: bool = False) -> str:
    """Preserve ordered cells in print tables; optionally support weighted tracks and forward spans."""
    if not re.search(r'grid-template-columns|display\s*:\s*(?:inline-)?grid',markup,re.I): return markup
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack: raise ValueError('Exercise layout tags must be balanced')
    changed=False

    def visit(node):
        """Transform explicit tracks without reordering cells or accepting named/positioned areas."""
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
        tracks=values.get('grid-template-columns','')
        columns=equal_columns(tracks)
        weights=[1.0]*columns if columns else []
        if columns is None and allow_weighted:
            tokens=tracks.split()
            if 1<=len(tokens)<=4 and all(re.fullmatch(r'(?:[1-9]\d*(?:\.\d+)?|0?\.\d+)fr',t) for t in tokens):
                weights=[float(t[:-2]) for t in tokens]
                if all(0<w<=100 for w in weights): columns=len(weights)
        unsupported={k for k in values if k.startswith('grid-') and k!='grid-template-columns'}
        if not grid or columns is None or unsupported or attrs.get('data-content'):
            raise ValueError('Use a simple 1-4 equal-column grid or a normal print table; complex grid placement needs an explicit layout repair')
        cells=[c for c in node['children'] if not isinstance(c,str) or c.strip()]
        if not cells or any(isinstance(c,str) or 'comment' in c for c in cells):
            raise ValueError('Printable grid cells must be separate content containers')
        gap=values.get('gap','0mm').split()
        if len(gap) not in {1,2}: raise ValueError('Printable grid gap needs one or two absolute lengths')
        row=values.get('row-gap',gap[0]);col=values.get('column-gap',gap[-1])
        row,col=print_gap(row),print_gap(col)
        spans=[]
        for cell in cells:
            declarations_cell=tinycss2.parse_declaration_list(dict(cell['attrs']).get('style','') or '',skip_comments=True,skip_whitespace=True)
            if any(d.type!='declaration' for d in declarations_cell):
                raise ValueError('Printable grid cells need valid inline styles')
            positions={d.lower_name:tinycss2.serialize(d.value).strip() for d in declarations_cell if d.lower_name.startswith('grid-')}
            span=1
            if positions:
                column=positions.get('grid-column','auto')
                matched=re.fullmatch(r'span\s+([1-4])',column)
                if not allow_weighted or set(positions)-{'grid-column'} or not (column in {'auto','1 / -1','1/-1'} or matched):
                    raise ValueError('Use a simple 1-4 equal-column grid or a normal print table; complex grid placement needs an explicit layout repair')
                span=int(matched[1]) if matched else columns if column!='auto' else 1
                if span>columns: raise ValueError('Printable grid span exceeds its column count')
                style_cell=tinycss2.serialize([d for d in declarations_cell if not d.lower_name.startswith('grid-')])
                cell['attrs']=[(k,v) for k,v in cell['attrs'] if k!='style']+[('style',style_cell)]
            spans.append(span)
        kept=[d for d in declarations if d.lower_name not in {'display','grid-template-columns','gap','row-gap','column-gap'}]
        attrs['style']=tinycss2.serialize(kept)+';display:block'
        node['attrs']=list(attrs.items())
        rows=[];current=[];occupied=0

        def add_cell(cell, span):
            """Retain source order and allocate proportional widths without absolute placement."""
            nonlocal occupied
            width=sum(weights[occupied:occupied+span])/sum(weights)*100
            cell_attrs=[('style',f'vertical-align:top;padding:0;width:{width:.6f}%')]
            if span>1: cell_attrs.append(('colspan',str(span)))
            current.append({'tag':'td','attrs':cell_attrs,'children':[] if cell is None else [cell]})
            occupied+=span

        def finish_row():
            """Pad only the unused final tracks; keep every original cell intact."""
            nonlocal current,occupied
            if not current:return
            if occupied<columns:add_cell(None,columns-occupied)
            rows.append({'tag':'tr','attrs':[],'children':current})
            current=[];occupied=0

        for cell,span in zip(cells,spans):
            if occupied+span>columns:finish_row()
            add_cell(cell,span)
            if occupied==columns:finish_row()
        finish_row()
        layout = 'auto' if len(set(weights))>1 else 'fixed'
        node['children']=[{'tag':'table','attrs':[('style',
            f'width:100%;table-layout:{layout};border-spacing:{col} {row}')],
            'children':[{'tag':'tbody','attrs':[],'children':rows}]}]
        changed=True

    for node in parser.root: visit(node)
    return ''.join(literal_html(n) for n in parser.root) if changed else markup
