"""Retain two-column source-card relationships while sharing space between art and a task."""
from copy import deepcopy
import math
import re

from core.content_binding import CanonicalTextContainers, bind_formatted_canonical_text
from core.page_contract import compile_exercise
from core.print_grid import literal_html


def content_slots(node):
    """Read semantic slots without flattening source groups or question workspaces."""
    if isinstance(node,str) or 'comment' in node:
        return set()
    own=dict(node['attrs']).get('data-content')
    return ({own} if own else set())|set().union(*(content_slots(child) for child in node['children']))


def compact_card_node(node, font):
    """Remove decorative text clamps; retain every independent blank panel and data cell."""
    node=deepcopy(node)
    if isinstance(node,str) or 'comment' in node:
        return node
    if not content_slots(node) and not re.search(r'\w',re.sub(r'<[^>]*>','',literal_html(node)).replace('_','')):
        return node  # Keep the original writing surface, including its height and border.
    discarded={'width','height','min-width','max-width','min-height','max-height',
        'display','flex','flex-direction','flex-wrap','flex-basis','flex-grow','flex-shrink',
        'align-items','justify-content','gap','row-gap','column-gap'}
    attrs=[]
    for key,value in node['attrs']:
        if key=='style':
            value=';'.join(part for part in (value or '').split(';')
                if part.split(':',1)[0].strip().lower() not in discarded
                and not part.split(':',1)[0].strip().lower().startswith(('padding','margin')))
            value+=f';font-size:{font}pt;line-height:1.15;margin:0;padding:0'
        attrs.append((key,value))
    if not any(key=='style' for key,_ in attrs):
        attrs.append(('style',f'font-size:{font}pt;line-height:1.15;margin:0;padding:0'))
    node['attrs']=attrs
    node['children']=[compact_card_node(child,font) for child in node['children']]
    return node


def source_card_layouts(page, minimum_font, visual_area):
    """Offer lossless layouts for an existing paired source-card composition.

    Only two declared, disjoint source columns qualify. The original card order,
    labels, all task wording, answers, image identity and blank writing heights
    survive. Each candidate still requires the normal measured print checks.
    """
    config=page.get('_recovery_config') or {}
    if (not config.get('stimulus_limit') or not isinstance(page.get('exercise'),dict)
            or page['exercise'].get('render_mode')!='authored'
            or not isinstance(page.get('images'),list) or len(page['images'])!=1
            or not 0<visual_area<=14000):
        return
    try:
        checked=deepcopy(page);blocks={}
        compile_exercise(checked,config,page.get('_recovery_title','Source-card activity'),blocks_out=blocks)
        parser=CanonicalTextContainers(blocks)
        parser.feed(bind_formatted_canonical_text(checked['source_layout'],blocks));parser.close()
        if parser.stack: return
        pairs=[]

        def find_pair(node):
            """Recognize two peer source columns, not arbitrary groups of text."""
            if isinstance(node,str) or 'comment' in node: return
            children=[child for child in node['children'] if not isinstance(child,str) or child.strip()]
            style=dict(node['attrs']).get('style','') or ''
            row=re.search(r'display\s*:\s*flex\b',style,re.I) and not re.search(r'flex-direction\s*:\s*(?:column|row-reverse)',style,re.I)
            if len(children)==2 and row:
                groups=[content_slots(child) for child in children]
                allowed=lambda group: group and all(slot.startswith(('stimulus_','caption_')) for slot in group)
                if (all(allowed(group) and sum(s.startswith('stimulus_') for s in group)>=2 for group in groups)
                        and not groups[0]&groups[1] and not re.search(r'<img\b',literal_html(node),re.I)):
                    pairs.append((node,children));return
            for child in node['children']: find_pair(child)

        for node in parser.root: find_pair(node)
        if len(pairs)!=1: return
        pair,columns=pairs[0];seen=set();metadata=set();contexts=[];questions=[];workspaces=[];assets=[]

        def collect(node):
            """Retain complete task containers and all remaining declared content once."""
            if isinstance(node,str):
                if node.strip() and node.strip() not in {':',';',',','|','•'}:
                    raise ValueError('Unbound text cannot be discarded')
                return
            if 'comment' in node: raise ValueError('Keep comments for strict validation')
            owned=content_slots(node)
            if node is pair:
                if seen&owned: raise ValueError('Repeated source content')
                seen.update(owned);return
            slot=dict(node['attrs']).get('data-content')
            if owned and owned<= {'title','name','date'}:
                seen.update(owned);metadata.update(owned);return
            question_slots={slot for slot in owned if slot.startswith('question_')}
            if len(question_slots)==1 and owned==question_slots and not re.search(r'<img\b',literal_html(node),re.I):
                if seen&owned: raise ValueError('Repeated task content')
                seen.update(owned);questions.append(literal_html(compact_card_node(node,minimum_font)));return
            if slot:
                if slot in seen: raise ValueError('Repeated content slot')
                seen.add(slot);contexts.append(literal_html(compact_card_node(node,minimum_font)));return
            if node['tag']=='img':
                aid=dict(node['attrs']).get('data-asset')
                if not aid: raise ValueError('Do not replace computed graphics')
                assets.append(aid);return
            rendered=literal_html(node)
            if not owned and not re.search(r'<img\b',rendered,re.I) and not re.search(r'\w',re.sub(r'<[^>]*>','',rendered).replace('_','')):
                workspaces.append(rendered);return
            for child in node['children']: collect(child)

        for node in parser.root: collect(node)
        if set(blocks)-{'name','date'}-seen or assets!=[checked['images'][0]['id']] or not questions:
            return
        side=math.ceil(math.sqrt(visual_area*1.04))
        if not 70<=side<=100: return
        accent='#1e3a8a';wash='#eef4fa'
        header=f'<h1 data-content="title" style="font-size:{minimum_font+4}pt;color:{accent};margin:0 0 1mm"></h1>'
        for name in ('name','date'):
            if name in metadata: header+=f'<span data-content="{name}" style="font-size:{minimum_font}pt;margin-right:3mm"></span> '
        header+='<br/>'+''.join(contexts)
        cards='<table style="width:175mm;table-layout:fixed;border-collapse:collapse;margin:1mm 0"><tr>'
        for column in columns:
            cards+=f'<td style="width:87.5mm;vertical-align:top;padding:1mm;border:0.3mm solid {accent};background-color:{wash}">'+literal_html(compact_card_node(column,minimum_font))+'</td>'
        cards+='</tr></table>'
        art=f'<img data-asset="{assets[0]}" style="width:{side}mm;height:{side}mm;object-fit:contain"/>'
        for art_first in (True,False):
            art_cell=f'<td style="width:{side+2}mm;vertical-align:top;padding:0 1mm 0 0">{art}</td>'
            task_cell=f'<td style="width:{173-side}mm;vertical-align:top;padding:0">{questions[0]}</td>'
            body='<table style="width:175mm;table-layout:fixed;border-collapse:collapse;margin:1mm 0"><tr>'+(art_cell+task_cell if art_first else task_cell+art_cell)+'</tr></table>'
            result=deepcopy(page);result['exercise']=deepcopy(checked['exercise'])
            result['html']=header+cards+body+''.join(questions[1:])+''.join(workspaces)
            yield result
    except (ValueError,TypeError,KeyError,IndexError):
        return
