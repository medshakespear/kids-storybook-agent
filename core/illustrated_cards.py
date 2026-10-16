"""Reflow explicitly paired illustrated source cards without duplicate source captions."""
from copy import deepcopy
import math
import re

from core.content_binding import CanonicalTextContainers
from core.page_contract import compile_exercise


def illustrated_source_cards(page, minimum_font, visual_area):
    """Keep existing image/source pairings in a measured two-column card layout.

    Only two or four unambiguous cards qualify. Identical source-label/body
    captions on that same card are redundant representations, not new evidence.
    Other captions, text, graphics or independent work areas prevent this fallback.
    """
    config=page.get('_recovery_config') or {}
    exercise=page.get('exercise',{})
    images=page.get('images',[])
    if (not config.get('student_workbook') or exercise.get('render_mode')!='authored'
            or not isinstance(images,list) or len(images) not in (2,4)
            or not 0<visual_area<=14000):return
    try:
        checked=deepcopy(page);blocks={}
        compile_exercise(checked,config,page.get('_recovery_title','Source cards'),blocks_out=blocks)
        parser=CanonicalTextContainers({});parser.feed(checked['source_layout']);parser.close()
        if parser.stack:return
        sources=checked['exercise'].get('stimuli',[])
        if len(sources)!=len(images):return
        by_slot={'stimulus_'+s['id']:s for s in sources}
        captions={'caption_'+c['id']:c for c in checked['exercise'].get('captions',[])}
        pairs=[];seen_slots=[];seen_assets=[]

        def norm(value):
            """Compare complete retained wording, allowing whitespace formatting only."""
            return ' '.join(value.split())

        def scan(node):
            """Identify the smallest existing container owning one image and source."""
            if isinstance(node,str):
                if node.strip():raise ValueError('Keep independent printed wording')
                return [],[]
            if 'comment' in node:raise ValueError('Keep comments')
            attrs=dict(node['attrs']);slot=attrs.get('data-content')
            if slot:
                seen_slots.append(slot)
                return [slot],[]
            if node['tag']=='img':
                asset=attrs.get('data-asset')
                if not asset:raise ValueError('Keep computed graphics')
                seen_assets.append(asset)
                return [],[asset]
            if all(isinstance(c,str) and not c.strip() for c in node['children']) and re.search(r'(?:height|padding|border)\s*:',attrs.get('style','')):
                raise ValueError('Keep independent blank workspace')
            slots=[];assets=[]
            for child in node['children']:
                child_slots,child_assets=scan(child);slots+=child_slots;assets+=child_assets
            owned=[s for s in slots if s in by_slot]
            if len(owned)==1 and len(assets)==1:
                source=by_slot[owned[0]]
                duplicate=[]
                for s in slots:
                    if s==owned[0]:continue
                    caption=captions.get(s)
                    if not caption or norm(caption['text']) not in {norm(source['text']),norm(source.get('label',''))}:
                        return slots,assets
                    duplicate.append(s)
                pairs.append((owned[0],assets[0],duplicate))
                # A claimed card cannot be claimed again by an ancestor.
                return ['__claimed_card__'],[]
            return slots,assets

        for node in parser.root:scan(node)
        if len(pairs)!=len(images) or sorted(seen_assets)!=sorted(i['id'] for i in images):return
        if len(set(seen_slots))!=len(seen_slots):return
        discarded={s for _,_,labels in pairs for s in labels}
        paired_sources={s for s,_,_ in pairs}
        required=set(blocks)-{'name','date'}
        other=required-paired_sources-discarded-{'title','directions'}
        if any(not s.startswith('question_') for s in other):return
        if set(captions)!=discarded:return
        if not required<=set(seen_slots):return
        result=deepcopy(page);result['exercise']=deepcopy(checked['exercise'])
        result['exercise']['captions']=[]
        result['_inline_source_labels']=True
        colors=re.findall(r'#[0-9a-fA-F]{6}\b',page['html'])
        accent=colors[0] if colors else '#167E80'
        side=math.ceil(math.sqrt(visual_area*1.02/len(images)))
        if side>70:return
        text_style=f'font-size:{minimum_font}pt;line-height:1.15;margin:0;padding:0'
        header=(f'<h1 data-content="title" style="font-size:{minimum_font+3}pt;line-height:1.15;'
                f'color:{accent};background-color:#FFF3E3;padding:1mm;margin:0 0 1mm"></h1>')
        header+=' '.join(f'<span data-content="{s}" style="{text_style}"></span>' for s in ('name','date') if s in seen_slots)
        header+=f'<p data-content="directions" style="{text_style};margin:1mm 0"></p>'
        rows=[]
        for offset in range(0,len(pairs),2):
            cells=[]
            for source,asset,_ in pairs[offset:offset+2]:
                cells.append(f'<td style="width:93mm;vertical-align:top;padding:0 1mm 1mm 0">'
                    '<table style="width:92mm;table-layout:fixed;border-collapse:collapse;background-color:#FFF8F0"><tr>'
                    f'<td style="width:{side}mm;vertical-align:top;padding:0"><img data-asset="{asset}" '
                    f'style="width:{side}mm;height:{side}mm;object-fit:contain"/></td>'
                    f'<td style="vertical-align:top;padding:0 1mm"><p data-content="{source}" style="{text_style}"></p></td>'
                    '</tr></table></td>')
            rows.append('<tr>'+''.join(cells)+'</tr>')
        body='<table style="width:186mm;table-layout:fixed;border-collapse:collapse">'+''.join(rows)+'</table>'
        tail=''.join(f'<div data-content="question_{q["id"]}" style="{text_style};margin-top:1mm"></div>'
            for q in result['exercise']['questions'])
        result['html']=header+body+tail
        yield result
    except (ValueError,TypeError,KeyError,IndexError):return
