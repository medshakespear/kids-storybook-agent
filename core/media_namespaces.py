"""Keep authored illustration references separate from computed puzzle references."""
import re
from core.content_binding import CanonicalTextContainers
from core.print_grid import literal_html


def normalize_authored_media(page: dict) -> None:
    """Rebind only an authored image whose visual-style ID names declared artwork.

    Exact-mode references and unknown IDs remain strict. No computed mechanism,
    image prompt, asset count, source, task or answer is replaced or invented.
    """
    exercise=page.get('exercise',{})
    if exercise.get('render_mode')!='authored' or exercise.get('visual'):return
    declared={a['id'] for a in page.get('images',[]) if isinstance(a,dict) and isinstance(a.get('id'),str)}
    parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
    if parser.stack:return
    changed=False

    def visit(node):
        """Correct the namespace only for an explicit, unambiguous raster-image ID."""
        nonlocal changed
        if isinstance(node,str) or 'comment' in node:return
        attrs=dict(node['attrs'])
        if len(attrs)!=len(node['attrs']):return
        visual=attrs.get('data-visual')
        if node['tag']=='img' and isinstance(visual,str) and not attrs.get('data-content'):
            aid=re.sub(r'[\s-]+','_',visual.strip().casefold())
            if aid in declared and attrs.get('data-asset',aid)==aid:
                node['attrs']=[(key,value) for key,value in node['attrs'] if key not in {'data-visual','data-asset'}]+[('data-asset',aid)]
                changed=True
        for child in node['children']:visit(child)

    for node in parser.root:visit(node)
    if changed:page['html']=''.join(literal_html(node) for node in parser.root)
