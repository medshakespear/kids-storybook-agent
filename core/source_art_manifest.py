"""Expand an explicitly numbered source-card art series from retained content."""
from core.content_binding import CanonicalTextContainers
import re


def expand_source_art(page: dict, config: dict) -> None:
    """Derive separate step briefs only from an unambiguous existing card series.

    One shared art brief may be expanded to 2-4 explicitly numbered HTML assets
    when each belongs to its own declared source card. Other mismatches remain
    errors. Each resulting image is generated once from that card's source text.
    """
    if not config.get('student_workbook') or page.get('exercise',{}).get('render_mode')!='authored':return
    images=page.get('images')
    if not isinstance(images,list) or len(images)!=1 or not isinstance(images[0],dict):return
    base=images[0];aid=base.get('id');prompt=base.get('prompt')
    if not isinstance(aid,str) or not isinstance(prompt,str) or not prompt.strip():return
    sources={'stimulus_'+s['id']:s for s in page['exercise'].get('stimuli',[]) if isinstance(s,dict) and isinstance(s.get('id'),str)}
    parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
    if parser.stack:return
    refs=[];pairs=[]

    def visit(node):
        """Associate a numbered asset with the source inside its nearest card."""
        if isinstance(node,str) or 'comment' in node:return [],[]
        attrs=dict(node['attrs']);slot=attrs.get('data-content')
        if slot:return [slot],[]
        if node['tag']=='img':
            ref=attrs.get('data-asset');refs.append(ref);return [],[ref]
        slots=[];assets=[]
        for child in node['children']:
            s,a=visit(child);slots+=s;assets+=a
        own=[s for s in slots if s in sources]
        if len(own)==1 and len(assets)==1 and all(s in sources or s.startswith('caption_') for s in slots):
            pairs.append((assets[0],sources[own[0]]));return ['__claimed__'],[]
        return slots,assets

    for node in parser.root:visit(node)
    if not 2<=len(refs)<=4 or len(set(refs))!=len(refs) or len(pairs)!=len(refs):return
    if {ref for ref,_ in pairs}!=set(refs) or len({s['id'] for _,s in pairs})!=len(refs):return
    if set(refs)!={aid+'_'+str(i) for i in range(1,len(refs)+1)}:return
    expanded=[]
    for ref,source in pairs:
        text=source.get('text')
        if not isinstance(text,str) or not text.strip() or len(ref)>31:return
        brief=prompt.strip()+' Depict this specific process card: '+text.strip()+' No printed words or answer marks.'
        if len(brief)>650:return  # Do not truncate a card or silently discard its shared style.
        expanded.append({'id':ref,'prompt':brief})
    page['images']=expanded
