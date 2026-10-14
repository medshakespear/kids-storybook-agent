"""Fit a verified computed puzzle together with every declared supporting illustration."""
from copy import deepcopy
import math
import re

from core.content_binding import CanonicalTextContainers
from core.missing_exact_context import recover_missing_exact_context
from core.page_contract import compile_exercise
from core.task_visuals import page_visuals


def exact_artwork_layout(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Use a readable puzzle column and a context/art column, preserving every task.

    Missing declared image references are restored from their existing manifest;
    no new image, prompt, source, question or answer is invented. This is only a
    candidate: semantic compilation and measured print checks must still accept it.
    """
    images=page.get('images')
    if (not isinstance(page.get('exercise'),dict) or page['exercise'].get('render_mode')!='exact'
            or not isinstance(images,list) or not 1<=len(images)<=4
            or any(not isinstance(a,dict) or a.get('local_template') for a in images)
            or not 0<visual_area<=22000):
        return None
    try:
        from core.layout_recovery import recovery_profile,supporting_slot_ids
        checked=recover_missing_exact_context(page)
        parser=CanonicalTextContainers({});parser.feed(checked['html']);parser.close()
        if parser.stack: return None
        refs=[]

        def visit(node):
            """Collect media references and protect independent dimensioned writing panels."""
            if isinstance(node,str): return
            if 'comment' in node: raise ValueError('Keep comments for strict validation')
            attrs=dict(node['attrs'])
            if node['tag']=='img' and attrs.get('data-asset'): refs.append(attrs['data-asset'])
            empty=not any(isinstance(c,dict) or c.strip() for c in node['children'])
            if (node['tag'] not in {'img','br'} and not attrs.get('data-content') and empty
                    and re.search(r'(?:^|;)\s*(?:height|min-height)\s*:\s*[1-9][0-9.]*',attrs.get('style',''))):
                raise ValueError('Cannot discard independent writing panels')
            for child in node['children']: visit(child)

        for node in parser.root: visit(node)
        ids=[a['id'] for a in images]
        if len(set(ids))!=len(ids) or any(ref not in ids or refs.count(ref)>1 for ref in refs): return None
        for aid in ids:
            if aid not in refs:
                checked['html']+=f'<img data-asset="{aid}" style="width:42mm;height:42mm"/>'
        compile_exercise(checked,recovery_profile(page,minimum_font),
            page.get('_recovery_title','Computed activity'),defer_visual_sizing=True)
        visuals=page_visuals(checked)
        if len(visuals)!=1: return None
        vid,(svg,_)=next(iter(visuals.items()))
        width=float(re.search(r'<svg[^>]*width="([0-9.]+)"',svg)[1])
        height=float(re.search(r'<svg[^>]*height="([0-9.]+)"',svg)[1])
        smallest=min(float(value) for value in re.findall(r'font-size="([0-9.]+)"',svg))
        scale=max(math.sqrt(visual_area/(width*height)),minimum_font*25.4/(72*smallest))*1.025
        w,h=math.ceil(width*scale),math.ceil(height*scale)
        if w>131 or h>195: return None
        accent='#167E80';wash='#EAF5F2'
        style=f'font-size:{minimum_font}pt;line-height:1.15;margin:0 0 2mm'
        header=f'<h1 data-content="title" style="font-size:{minimum_font+4}pt;color:{accent};margin:0 0 2mm"></h1>'
        header+=f'<p data-content="name" style="{style}"></p>'
        if re.search(r'\bdata-content\s*=\s*[\'\"]date[\'\"]',checked['source_layout']):
            header+=f'<p data-content="date" style="{style}"></p>'
        sidebar=''.join(f'<img data-asset="{aid}" style="width:42mm;height:42mm;object-fit:contain"/>' for aid in ids)
        sidebar+=''.join(f'<p data-content="{slot}" style="{style}"></p>'
            for slot in supporting_slot_ids(checked,checked['exercise']))
        body=(f'<table style="width:175mm;table-layout:fixed;border-collapse:collapse;margin:0 0 2mm"><tr>'
            f'<td style="width:{w+2}mm;vertical-align:top;padding:0 2mm 0 0;background-color:{wash}">'
            f'<img data-visual="{vid}" style="width:{w}mm;height:{h}mm"/></td>'
            f'<td style="width:{173-w}mm;vertical-align:top;padding:0">{sidebar}</td></tr></table>')
        tail=''.join(f'<div data-content="question_{question["id"]}" style="{style};padding:1mm;border-top:0.4mm solid {accent}"></div>'
            for question in checked['exercise'].get('questions',[]))
        result=deepcopy(page);result['exercise']=deepcopy(checked['exercise']);result['html']=header+body+tail
        return result
    except (ValueError,TypeError,KeyError,IndexError,ZeroDivisionError):
        return None
