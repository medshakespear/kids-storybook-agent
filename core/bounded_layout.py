"""Bounded reflow of verified authored content with a shared text/art/workspace budget."""
from copy import deepcopy
import math
import re

from core.content_binding import CanonicalTextContainers, bind_formatted_canonical_text
from core.page_contract import compile_exercise
from core.print_grid import literal_html


def bounded_authored_layouts(page: dict, minimum_font: int, visual_area: float):
    """Offer bounded layouts of the same content, never smaller fonts or writing panels.

    Gemini's valid composition remains preferred. These fallback candidates are
    for mixed authored pages only, after content verification. Real WeasyPrint
    measurement must accept one before it can become a published page.
    """
    config=page.get('_recovery_config',{})
    if (not config.get('stimulus_limit') or not isinstance(page.get('exercise'),dict)
            or page['exercise'].get('render_mode')!='authored'
            or not isinstance(page.get('images'),list) or not 1<=len(page['images'])<=4
            or not 0<visual_area<=22000):
        return
    try:
        source=page
        if len(page['images'])==1 and '<table' in page.get('html','').lower():
            from core.layout_recovery import retained_table_artwork_recovery
            separated=retained_table_artwork_recovery(page,minimum_font,visual_area)
            if separated is not None: source=separated
        checked=deepcopy(source);blocks={}
        compile_exercise(checked,config,page.get('_recovery_title','Internal layout check'),blocks_out=blocks)
        markup=bind_formatted_canonical_text(checked['source_layout'],blocks)
        parser=CanonicalTextContainers(blocks);parser.feed(markup);parser.close()
        if parser.stack: return
        contexts=[];questions=[];workspaces=[];assets=[];metadata=set();seen=set()

        def slots(node):
            """Read semantic bindings while keeping real data tables as atomic units."""
            if isinstance(node,str) or 'comment' in node: return set()
            own=dict(node['attrs']).get('data-content')
            return ({own} if own else set())|set().union(*(slots(c) for c in node['children']))

        def adjust(node, compact=False):
            """Remove text width/height clamps, preserving cell relationships and styles."""
            if isinstance(node,str) or 'comment' in node: return
            blocked={'width','min-width','max-width','height','min-height','max-height',
                     'display','flex-basis','flex-shrink','flex-grow','flex-direction','align-items','justify-content'}
            attrs=[]
            for key,value in node['attrs']:
                if key=='style':
                    value=';'.join(d for d in (value or '').split(';')
                                   if d.split(':',1)[0].strip().lower() not in blocked
                                   and not d.split(':',1)[0].strip().lower().startswith(('margin','padding')))
                    value+=f';font-size:{minimum_font}pt;line-height:{1.15 if compact else 1.2};margin:0 0 {0 if compact else 1.5}mm;padding:{0.5 if compact else 1}mm'
                    if node['tag']=='table': value+=';width:100%;table-layout:'+('auto' if compact else 'fixed')
                attrs.append((key,value))
            if not any(k=='style' for k,_ in attrs):
                attrs.append(('style',f'font-size:{minimum_font}pt;line-height:{1.15 if compact else 1.2};margin:0 0 {0 if compact else 1.5}mm;padding:{0.5 if compact else 1}mm'+
                    (';width:100%;table-layout:'+('auto' if compact else 'fixed') if node['tag']=='table' else '')))
            if compact and node['tag'] in {'table','td','th'}:
                # Auto columns must measure complete words, not break a proper
                # name or heading mid-word merely to favor another column.
                attrs=[(k,v+';overflow-wrap:normal' if k=='style' else v) for k,v in attrs]
            if compact and node['tag'] in {'table','thead','tbody','tfoot','tr'}:
                attrs=[(k,v+';padding:0' if k=='style' else v) for k,v in attrs]
            node['attrs']=attrs
            for child in node['children']: adjust(child,compact)

        def collect(node):
            """Collect every required slot, asset, table and independent blank work surface."""
            if isinstance(node,str):
                if not node.strip(): return
                if node.strip() in {':',';',',','|','•'}:
                    return  # Decorative separators do not define a student task.
                if re.fullmatch(r'[_\s|]{3,}|(?:\[[_\s]*\]\s*)+',node.strip()):
                    workspaces.append('<p>'+literal_html(node)+'</p>');return
                raise ValueError('Unbound literal text cannot be discarded by bounded reflow')
            if 'comment' in node: raise ValueError('Retain comments for strict validation')
            attrs=dict(node['attrs']);slot=attrs.get('data-content')
            if not slot:
                pieces=[parser.plain_text(c) for c in node['children']]
                value=' '.join(''.join(pieces).split()).casefold() if all(p is not None for p in pieces) else ''
                matches=[key for key,text in parser.text_blocks.items() if value and value==text]
                if len(matches)==1:
                    slot=matches[0];node['attrs'].append(('data-content',slot));node['children']=[]
            if slot:
                if slot in seen:
                    if slot in {'name','date'}: return
                    raise ValueError('Repeated content cannot be removed during bounded reflow')
                seen.add(slot)
                if slot in {'title','name','date'}:
                    metadata.add(slot);return
                if slot.startswith('question_'):
                    questions.append(slot);return
                adjust(node);contexts.append(literal_html(node));return
            if node['tag']=='img':
                if attrs.get('data-asset'): assets.append(attrs['data-asset']);return
                raise ValueError('Authored reflow cannot replace a computed visual')
            if node['tag']=='table':
                owned=slots(node)
                if owned and not any(s in {'title','name','date','directions'} or s.startswith('question_') for s in owned):
                    # Actual source/data tables stay together, including spans.
                    if re.search(r'<img\b',literal_html(node),re.I):
                        raise ValueError('An image/data table needs its retained-layout recovery')
                    if seen&owned: raise ValueError('Table content repeats another slot')
                    seen.update(owned);adjust(node);contexts.append(literal_html(node));return
            rendered=literal_html(node)
            if (not slots(node) and not re.search(r'<img\b',rendered,re.I)
                    and not re.search(r'\w',re.sub(r'<[^>]*>','',rendered).replace('_',''))):
                workspaces.append(rendered);return
            for child in node['children']: collect(child)

        for node in parser.root: collect(deepcopy(node))
        required=set(blocks)-{'name','date'}
        if not required.issubset(seen) or sorted(assets)!=sorted(a['id'] for a in checked['images']): return
        colors=re.findall(r'#[0-9a-fA-F]{6}\b',page['html'])
        accent=colors[0] if colors else '#167E80'
        wash=config.get('wash','#EAF5F2')
        text_style=f'font-size:{minimum_font}pt;line-height:1.2;margin:0 0 2mm'
        header=f'<h1 data-content="title" style="font-size:{minimum_font+5}pt;color:{accent};background-color:{wash};padding:2mm;margin:0 0 2mm;border-radius:3mm"></h1>'
        for field in ('name','date'):
            if field in metadata: header+=f'<span data-content="{field}" style="{text_style}"></span> '
        if metadata&{'name','date'}: header+='<br/>'
        tail=''.join(f'<div data-content="{slot}" style="{text_style};padding:1mm;border-top:0.4mm solid {accent}"></div>' for slot in questions)
        tail+=''.join(workspaces)

        def artwork(width):
            """Render every declared illustration above its combined visual-area floor."""
            # Generated assets use square canvases. Square frames keep the
            # actual illustration large instead of meeting the area budget
            # with a wide box whose letterboxed picture remains too small.
            side=math.ceil(math.sqrt(visual_area*1.04/len(assets)))
            if side>width: raise ValueError('Artwork cannot fit in this column')
            columns=min(len(assets),max(1,int((width+1)/(side+1))))
            rows=[]
            for offset in range(0,len(assets),columns):
                cells=''.join(f'<td style="padding:0 1mm 1mm 0;vertical-align:top"><img data-asset="{aid}" '
                    f'style="width:{side}mm;height:{side}mm;object-fit:contain"/></td>' for aid in assets[offset:offset+columns])
                rows.append('<tr>'+cells+'</tr>')
            if len(assets)==1:
                return f'<img data-asset="{assets[0]}" style="width:{side}mm;height:{side}mm;object-fit:contain"/>'
            return '<table style="border-collapse:collapse;border-spacing:0"><tbody>'+''.join(rows)+'</tbody></table>'

        if config.get('student_workbook') and len(assets)==1:
            # Use the full printable width. Nested margins and equal-width data
            # columns can otherwise consume the same height as the illustration.
            # Keep real rows/cells/spans, all wording and both answer heights.
            compact_contexts=[];directions=[];preface=[];table_contexts=[]
            for context in contexts:
                tree=CanonicalTextContainers(blocks);tree.feed(context);tree.close()
                for node in tree.root: adjust(node,compact=True)
                rendered=''.join(literal_html(n) for n in tree.root)
                if any('directions' in slots(n) for n in tree.root): directions.append(rendered)
                else:
                    compact_contexts.append(rendered)
                    (table_contexts if any(isinstance(n,dict) and n.get('tag')=='table' for n in tree.root) else preface).append(rendered)
            if table_contexts:
                # A source paragraph wraps into half as many lines at full
                # width. Put it above the art/table pair; do not squeeze three
                # real data columns and a paragraph into one narrow tall panel.
                directions.extend(preface);compact_contexts=table_contexts
            side=math.ceil(math.sqrt(visual_area))
            art=f'<td style="width:{side+2}mm;vertical-align:top;padding:0 2mm 0 0"><img data-asset="{assets[0]}" style="width:{side}mm;height:{side}mm;object-fit:contain"/></td>'
            context=f'<td style="width:{186-side-2}mm;vertical-align:top;padding:0">'+''.join(compact_contexts)+'</td>'
            compact_header=f'<h1 data-content="title" style="font-size:{minimum_font+3}pt;line-height:1.15;color:{accent};background-color:{wash};padding:1mm;margin:0 0 1mm"></h1>'
            compact_header+=' '.join(f'<span data-content="{field}" style="font-size:{minimum_font}pt"></span>' for field in ('name','date') if field in metadata)
            compact_header+=''.join(directions)
            compact_tail=''.join(f'<div data-content="{slot}" style="font-size:{minimum_font}pt;line-height:1.15;margin:1mm 0;padding:0"></div>' for slot in questions)+''.join(workspaces)
            if config.get('simple_exercises_only') and sum(len(re.findall(r'<th\b',c)) for c in compact_contexts)>=4:
                # Numeric tables need their own full-width region. Keep the same
                # image, data, typography and writing heights; measure this
                # compact stacked arrangement before a narrow side-by-side one.
                stacked=deepcopy(page);stacked['exercise']=deepcopy(checked['exercise'])
                stacked['html']=(compact_header+'<div style="text-align:center;margin:0 0 1mm">'
                    +artwork(175)+'</div>'+''.join(compact_contexts)+compact_tail)
                yield stacked
            result=deepcopy(page);result['exercise']=deepcopy(checked['exercise'])
            result['html']=compact_header+'<table style="width:186mm;table-layout:fixed;border-collapse:collapse"><tr>'+art+context+'</tr></table>'+compact_tail
            yield result

        if config.get('student_workbook') and len(assets)==2 and len(checked['exercise'].get('stimuli',[]))>=4:
            # A secondary picture beside the header leaves a broad main
            # artwork/source row and full-width handwriting below. Keep every
            # source label inline instead of spending one line per label.
            main_side=math.ceil(math.sqrt(visual_area*0.84))
            secondary_side=math.ceil(math.sqrt(max(1,visual_area-main_side**2)))
            compact_contexts=[];directions=[]
            for context in contexts:
                tree=CanonicalTextContainers(blocks);tree.feed(context);tree.close()
                for node in tree.root:
                    adjust(node,compact=True)
                    if isinstance(node,dict) and dict(node.get('attrs',[])).get('data-content','').startswith('stimulus_'):
                        # Six source cards otherwise pay twelve vertical padding
                        # bands. Keep horizontal inset, borders and every word.
                        node['attrs']=[(k,v+';padding:0 0.5mm' if k=='style' else v) for k,v in node['attrs']]
                rendered=''.join(literal_html(node) for node in tree.root)
                (directions if any('directions' in slots(node) for node in tree.root) else compact_contexts).append(rendered)
            compact_header=f'<h1 data-content="title" style="font-size:{minimum_font+3}pt;line-height:1.15;color:{accent};margin:0 0 1mm"></h1>'
            fields=set(metadata)&{'name','date'}
            if re.search(r'\bDate:\s*_+',page['html']):fields.add('date')
            compact_header+=' '.join(f'<span data-content="{field}" style="font-size:{minimum_font}pt"></span>' for field in ('name','date') if field in fields)
            compact_header+=''.join(directions)
            top=(f'<table style="width:186mm;table-layout:fixed;border-collapse:collapse;margin:0 0 1mm"><tr>'
                 f'<td style="width:{184-secondary_side}mm;vertical-align:top;padding:0 2mm 0 0">'+compact_header+'</td>'
                 f'<td style="width:{secondary_side}mm;vertical-align:top;padding:0"><img data-asset="{assets[1]}" style="width:{secondary_side}mm;height:{secondary_side}mm;object-fit:contain"/></td></tr></table>')
            body=(f'<table style="width:186mm;table-layout:fixed;border-collapse:collapse"><tr>'
                  f'<td style="width:{main_side+2}mm;vertical-align:top;padding:0 2mm 0 0"><img data-asset="{assets[0]}" style="width:{main_side}mm;height:{main_side}mm;object-fit:contain"/></td>'
                  f'<td style="width:{184-main_side}mm;vertical-align:top;padding:0">'+''.join(compact_contexts)+'</td></tr></table>')
            compact_tail=''.join(f'<div data-content="{slot}" style="font-size:{minimum_font}pt;line-height:1.15;margin:1mm 0;padding:0"></div>' for slot in questions)+''.join(workspaces)
            result=deepcopy(page);result['exercise']=deepcopy(checked['exercise'])
            result['_inline_source_labels']=True
            result['html']=top+body+compact_tail
            yield result

        # Full-width text preserves long sources and real data-table readability.
        variants=[artwork(175)+'<div style="'+text_style+'">'+''.join(contexts)+'</div>']
        for art_first in (True,False):
            art_width=math.ceil(math.sqrt(visual_area*1.04))+2 if config.get('student_workbook') and len(assets)==1 else 112
            art_cell=f'<td style="width:{art_width}mm;padding:0 2mm 0 0;vertical-align:top">'+artwork(art_width-2)+'</td>'
            text_cell=f'<td style="width:{175-art_width}mm;padding:0;vertical-align:top">'+''.join(contexts)+'</td>'
            variants.append('<table style="width:175mm;table-layout:fixed;border-collapse:collapse"><tr>'+
                            (art_cell+text_cell if art_first else text_cell+art_cell)+'</tr></table>')
        for body in variants:
            result=deepcopy(page);result['exercise']=deepcopy(checked['exercise'])
            result['html']=header+body+tail
            yield result
    except (ValueError,TypeError,KeyError,IndexError):
        return
