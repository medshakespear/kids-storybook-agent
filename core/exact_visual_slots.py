"""Recover missing or repeated references to the same verified computed diagram."""
import math
import re

from core.content_binding import CanonicalTextContainers
from core.print_grid import literal_html


def normalize_exact_visual_slots(markup: str, visuals: dict, minimum_font: int, visual_area: float) -> str:
    """Supply one known diagram or remove only redundant copies, preserving all other nodes.

    This only prepares a candidate. Normal content, font, area, collision and page
    bounds validation still runs. Unknown references and malformed attributes are
    left untouched so the strict validator can report them.
    """
    if len(visuals)!=1 or not 0<visual_area<=22000:
        return markup
    vid,(svg,_) = next(iter(visuals.items()))
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack: return markup
    references=[]

    def collect(node):
        """Read only genuine diagram images, never labels or asset illustrations."""
        if isinstance(node,str) or 'comment' in node: return
        if node['tag']=='img' and dict(node['attrs']).get('data-visual'):
            references.append(node)
        for child in node['children']: collect(child)

    for node in parser.root: collect(node)
    if any(dict(n['attrs']).get('data-visual')!=vid
           or len(dict(n['attrs']))!=len(n['attrs'])
           or any(k not in {'data-visual','style'} for k,_ in n['attrs']) for n in references):
        return markup
    if len(references)==1: return markup
    if not references:
        try:
            width=float(re.search(r'<svg[^>]*width="([0-9.]+)"',svg)[1])
            height=float(re.search(r'<svg[^>]*height="([0-9.]+)"',svg)[1])
            smallest=min(float(v) for v in re.findall(r'font-size="([0-9.]+)"',svg))
            scale=max(math.sqrt(visual_area/(width*height)),minimum_font*25.4/(72*smallest))*1.02
            w,h=math.ceil(width*scale),math.ceil(height*scale)
            if w>180 or h>230: return markup
        except (TypeError,IndexError,ValueError,ZeroDivisionError):
            return markup
        image={'tag':'img','attrs':[('data-visual',vid),('style',f'width:{w}mm;height:{h}mm')],'children':[]}
        index=next((i+1 for i,n in enumerate(parser.root) if isinstance(n,dict)
                    and dict(n.get('attrs',[])).get('data-content')=='title'),len(parser.root))
        parser.root.insert(index,image)
    else:
        duplicates={id(n) for n in references[1:]}

        def retain(node):
            """Remove only duplicate image nodes; retain their wrappers and writing areas."""
            if isinstance(node,dict) and 'children' in node:
                node['children']=[child for child in node['children'] if id(child) not in duplicates]
                for child in node['children']: retain(child)

        parser.root=[n for n in parser.root if id(n) not in duplicates]
        for node in parser.root: retain(node)
    return ''.join(literal_html(n) for n in parser.root)
