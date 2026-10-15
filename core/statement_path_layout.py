"""Fit complete printed reasoning routes without stacking art and every response."""
from copy import deepcopy
import math
import re

from core.content_binding import CanonicalTextContainers, bind_formatted_canonical_text
from core.card_layout import compact_card_node, content_slots
from core.page_contract import compile_exercise
from core.print_grid import literal_html


def statement_path_layouts(page: dict, minimum_font: int, visual_area: float):
    """Offer bounded card grids with full-size art beside the retained questions.

    Only a compiled authored statement path with one illustration qualifies.
    Source/data tables remain atomic; canonical facts, connections, questions,
    keys and every independent writing panel survive. The caller must still
    measure fonts, artwork, page count, bounds and overlaps on every candidate.
    This function never supplies a missing endpoint, branch or answer.
    """
    config=page.get('_recovery_config') or {}
    exercise=page.get('exercise') or {}
    if (not config.get('stimulus_limit') or not isinstance(exercise,dict)
            or exercise.get('render_mode')!='authored' or exercise.get('mechanic')!='statement_path'
            or not isinstance(page.get('images'),list) or len(page['images'])!=1
            or not 0<visual_area<=14000):
        return
    try:
        checked=deepcopy(page);blocks={}
        compile_exercise(checked,config,page.get('_recovery_title','Statement path'),blocks_out=blocks)
        from core.maze_intent import statement_path_issues
        if statement_path_issues(checked):
            return  # Geometry must not turn an incomplete route into an approved task.
        parser=CanonicalTextContainers(blocks)
        parser.feed(bind_formatted_canonical_text(checked['source_layout'],blocks));parser.close()
        if parser.stack: return
        seen=set();metadata=set();intro=[];cards=[];questions=[];workspaces=[];assets=[]

        def retain(owned):
            """Require each canonical source or question exactly once before recomposition."""
            if seen&owned: raise ValueError('Repeated route content needs a content repair')
            seen.update(owned)

        def collect(node):
            """Keep tables and writing panels whole; group only independently bound cards."""
            if isinstance(node,str):
                if not node.strip() or node.strip() in {':',';',',','|','•'}: return
                if re.fullmatch(r'[_\s|]{3,}|(?:\[[_\s]*\]\s*)+',node.strip()):
                    workspaces.append('<p>'+literal_html(node)+'</p>');return
                raise ValueError('Do not discard unbound route text')
            if 'comment' in node: raise ValueError('Comments require ordinary validation')
            attrs=dict(node['attrs']);slot=attrs.get('data-content');owned=content_slots(node)
            if slot:
                if owned!={slot}: raise ValueError('Nested route sources require binding repair')
                retain(owned)
                if slot in {'title','name','date'}: metadata.add(slot)
                elif slot.startswith('question_'): questions.append(slot)
                elif slot in {'directions','passage'}:
                    intro.append(literal_html(compact_card_node(node,minimum_font)))
                elif slot.startswith(('caption_','stimulus_')):
                    cards.append((False,literal_html(compact_card_node(node,minimum_font))))
                else: raise ValueError('Unknown route slot')
                return
            if node['tag']=='img':
                if not attrs.get('data-asset') or attrs.get('data-visual'):
                    raise ValueError('Do not replace computed graphics with art')
                assets.append(attrs['data-asset']);return
            if node['tag']=='table' and owned:
                if any(s in {'title','name','date','directions','passage'} or s.startswith('question_') for s in owned):
                    raise ValueError('Keep mixed task/data table relationships intact')
                if re.search(r'<img\b',literal_html(node),re.I):
                    raise ValueError('Do not flatten image/data table relationships')
                retain(owned)
                cards.append((True,literal_html(compact_card_node(node,minimum_font))))
                return
            rendered=literal_html(node)
            if (node['tag']!='br' and not owned and not re.search(r'<img\b',rendered,re.I)
                    and not re.search(r'\w',re.sub(r'<[^>]*>','',rendered).replace('_',''))):
                workspaces.append(rendered);return
            for child in node['children']: collect(child)

        for node in parser.root: collect(node)
        if (set(blocks)-{'name','date'}-seen or not questions
                or assets!=[checked['images'][0]['id']]):
            return
        side=math.ceil(math.sqrt(visual_area*1.04))
        if side>100: return
        accent='#167E80';wash='#EAF5F2'
        header=f'<h1 data-content="title" style="font-size:{minimum_font+4}pt;color:{accent};background-color:{wash};padding:2mm;margin:0 0 1mm;border-radius:3mm"></h1>'
        for field in ('name','date'):
            if field in metadata:
                header+=f'<span data-content="{field}" style="font-size:{minimum_font}pt;margin-right:3mm"></span> '
        if metadata&{'name','date'}: header+='<br/>'
        header+=''.join(intro)

        def grid(columns):
            """Lay independent cards in reading order; retain real source tables full width."""
            output=[];pending=[]

            def flush():
                """Emit a row-major card table with readable automatic text heights."""
                if not pending: return
                rows=[]
                for offset in range(0,len(pending),columns):
                    cells=pending[offset:offset+columns]
                    cells+=['']*(columns-len(cells))
                    rows.append('<tr>'+''.join(
                        f'<td style="width:{175/columns:.3f}mm;vertical-align:top;padding:1mm;border:0.3mm solid {accent};background-color:{wash}">{cell}</td>'
                        for cell in cells)+'</tr>')
                output.append('<table style="width:175mm;table-layout:fixed;border-collapse:collapse;margin:1mm 0"><tbody>'+''.join(rows)+'</tbody></table>')
                pending.clear()

            for atomic,card in cards:
                if atomic: flush();output.append(card)
                else: pending.append(card)
            flush()
            return ''.join(output)

        tasks=''.join(f'<div data-content="{slot}" style="font-size:{minimum_font}pt;line-height:1.2;margin:0 0 2mm"></div>' for slot in questions)
        art=f'<img data-asset="{assets[0]}" style="width:{side}mm;height:{side}mm;object-fit:contain"/>'
        for columns in (2,3):
            for art_first in (True,False):
                art_cell=f'<td style="width:{side+2}mm;vertical-align:top;padding:0 2mm 0 0">{art}</td>'
                task_cell=f'<td style="width:{173-side}mm;vertical-align:top;padding:0">{tasks}</td>'
                body='<table style="width:175mm;table-layout:fixed;border-collapse:collapse;margin:1mm 0"><tbody><tr>'+(art_cell+task_cell if art_first else task_cell+art_cell)+'</tr></tbody></table>'
                result=deepcopy(page);result['exercise']=deepcopy(checked['exercise'])
                result['html']=header+grid(columns)+body+''.join(workspaces)
                yield result
    except (ValueError,TypeError,KeyError,IndexError):
        return
