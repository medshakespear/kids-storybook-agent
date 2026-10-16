"""Measured reference/response sheets for dense varied activities that cannot fit one A4 page."""
from copy import deepcopy
import math
import re
import tinycss2
from core.content_binding import CanonicalTextContainers
from core.print_grid import literal_html


def continuation_boundaries(markup: str) -> int:
    """Count explicit physical boundaries in styles, never matching words in lesson text."""
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    count=0
    def visit(node):
        """Inspect only literal CSS declarations on retained elements."""
        nonlocal count
        if isinstance(node,str) or 'comment' in node:return
        style=dict(node['attrs']).get('style','') or ''
        for d in tinycss2.parse_declaration_list(style,skip_comments=True,skip_whitespace=True):
            if d.type=='declaration' and d.lower_name=='break-before' and tinycss2.serialize(d.value).strip()=='page':count+=1
        for child in node['children']:visit(child)
    for node in parser.root:visit(node)
    return count


def prefer_continuation(page: dict) -> bool:
    """Avoid repeated one-sheet trials for demonstrably dense reference/work combinations."""
    config=page.get('_recovery_config',{});exercise=page.get('exercise',{})
    if not config.get('allow_activity_continuations') or continuation_boundaries(page.get('html','')):return False
    questions=exercise.get('questions',[])
    response_height=sum(q.get('space_mm',0) for q in questions if isinstance(q,dict))
    templates=[a for a in page.get('images',[]) if a.get('local_template') and not a['local_template'].endswith('_reference')]
    if len(templates)==1 and len(page.get('images',[]))>=3 and response_height>=75:return True
    if response_height<100:return False
    words=sum(len(s.get('text','').split()) for s in exercise.get('stimuli',[]) if isinstance(s,dict))
    markup=page.get('html','');headers=len(re.findall(r'<th\b',markup));rows=len(re.findall(r'<tr\b',markup))
    if headers>=3 and words>=35 and len(page.get('images',[]))==2:return True
    if headers>=2 and rows>=5 and words>=65:return True
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close();extra=0
    from core.image_dimensions import length_mm
    def visit(node):
        """Measure extra empty work surfaces only, excluding image and source containers."""
        nonlocal extra
        if isinstance(node,str) or 'comment' in node:return
        attrs=dict(node['attrs'])
        if node['tag']=='div' and not attrs.get('data-content') and all(isinstance(c,str) and not c.strip() for c in node['children']):
            values={d.lower_name:tinycss2.serialize(d.value).strip() for d in tinycss2.parse_declaration_list(attrs.get('style',''),skip_comments=True,skip_whitespace=True) if d.type=='declaration'}
            extra+=max(length_mm(values.get('height','')) or 0,length_mm(values.get('min-height','')) or 0)
        for child in node['children']:visit(child)
    for node in parser.root:visit(node)
    return words>=70 and extra>=60


def continuation_layout(page: dict, font: int, visual_area: float):
    """Keep complete reference tables/art on sheet one and full responses on sheet two.

    This is a bounded opt-in fallback, not acceptance of arbitrary overflow. Both
    sheets must pass actual geometry, typography, artwork and answer-width checks.
    Every canonical field, meaningful asset and independent work surface survives.
    """
    config=page.get('_recovery_config',{})
    if (not config.get('allow_activity_continuations') or page.get('exercise',{}).get('render_mode')!='authored'
            or continuation_boundaries(page.get('html',''))):return
    from core.page_contract import compile_exercise
    from core.card_layout import content_slots,compact_card_node
    from core.work_templates import prepare_work_template,template_dimensions
    try:
        checked=deepcopy(page);blocks={}
        prepare_work_template(checked,config,page.get('_recovery_title','Activity'))
        compile_exercise(checked,config,page.get('_recovery_title','Activity'),blocks_out=blocks)
        parser=CanonicalTextContainers({});parser.feed(checked['source_layout']);parser.close()
        if parser.stack:return
        seen=[];references=[];responses=[];assets=[]

        def reference_markup(node):
            """Keep table cells and bordered cards comfortably inset at readable type sizes."""
            compact=compact_card_node(node,font)
            def inset(item):
                """Add breathing room without changing data rows, spans or text."""
                if isinstance(item,str) or 'comment' in item:return
                attrs=dict(item['attrs']);style=attrs.get('style','') or ''
                if item['tag'] in {'td','th'} or (item['tag']=='div' and re.search(r'(?:^|;)border\s*:',style)):
                    item['attrs']=[(k,v) for k,v in item['attrs'] if k!='style']+[('style',style+';padding:0.8mm 1mm')]
                for child in item['children']:inset(child)
            inset(compact)
            return literal_html(compact)

        def collect(node):
            """Keep tables atomic and send only questions and their extra blank panels to responses."""
            if isinstance(node,str):
                if node.strip():raise ValueError('Keep unbound wording')
                return
            if 'comment' in node:raise ValueError('Keep comments')
            attrs=dict(node['attrs']);slot=attrs.get('data-content')
            if slot:
                seen.append(slot)
                if slot in {'title','name','date','directions'}:return
                if slot.startswith('question_'):
                    responses.append(literal_html(compact_card_node(node,font)))
                else:references.append(reference_markup(node))
                return
            if node['tag']=='img':assets.append(attrs.get('data-asset'));return
            owned=content_slots(node)
            if node['tag']=='table':
                # The deterministic simple-workbook header is a blank metadata
                # table, not a reference-data table. Collect its fields normally
                # so it cannot disable the bounded continuation fallback.
                from core.workbook_checks import printed_words
                markup=literal_html(node)
                if (not owned and not printed_words(markup) and len(re.findall(r'<tr\b',markup))==1
                        and not re.search(r'<(?:img|th)\b|(?:min-|max-)?height\s*:|(?:border|background)[\w-]*\s*:',markup,re.I)):
                    # Moving metadata can leave a structurally empty header row.
                    # It has no printed cells, graphics or writing surface.
                    return
                if (owned and set(owned)<={'name','date'} and not printed_words(markup)
                        and not re.search(r'<img\b|(?:min-|max-)?height\s*:',markup,re.I)):
                    for child in node['children']:collect(child)
                    return
                if not owned or any(s in {'title','name','date','directions'} or s.startswith('question_') for s in owned) or re.search(r'<img\b',literal_html(node)):
                    raise ValueError('Retain mixed table relationships')
                seen.extend(owned);references.append(reference_markup(node));return
            if not owned and not re.search(r'<img\b',literal_html(node)):
                # Preserve original empty writing surfaces, including grouped
                # sentence lines. This fallback does not consolidate them away.
                empty=all(isinstance(c,str) and not c.strip() for c in node['children'])
                if empty and re.search(r'(?:height|min-height)\s*:\s*[1-9]',attrs.get('style','')):
                    if not responses:raise ValueError('An unassociated work surface needs its original layout')
                    responses.append(literal_html(node));return
            for child in node['children']:collect(child)

        for node in parser.root:collect(node)
        if len(seen)!=len(set(seen)) or not (set(blocks)-{'name','date'})<=set(seen):return
        images=checked['images']
        if sorted(assets)!=sorted(a['id'] for a in images) or not responses:return
        style=f'font-size:{font}pt;line-height:1.15;margin:0 0 1mm;padding:0'
        header=f'<h1 data-content="title" style="font-size:{font+3}pt;line-height:1.15;color:#167E80;background-color:#EAF5F2;padding:1mm;margin:0 0 1mm"></h1>'
        header+=' '.join(f'<span data-content="{s}" style="{style}"></span>' for s in ('name','date') if s in seen)
        header+=f'<p data-content="directions" style="{style}"></p>'
        templates=[a for a in images if a.get('local_template') and not a['local_template'].endswith('_reference')]
        decorative=[a for a in images if a not in templates]
        def artwork(asset,w,h):
            """Preserve each image identity and use its true printable template dimensions."""
            return f'<img data-asset="{asset["id"]}" style="width:{w:g}mm;height:{h:g}mm;object-fit:contain;display:block;margin:0 auto 1mm"/>'
        if templates:
            if len(templates)!=1 or len(decorative)>3:return
            if len(decorative)==1:
                header=('<table style="width:186mm;table-layout:fixed;border-collapse:collapse"><tr><td style="width:144mm;padding:0 2mm 0 0">'+header+'</td>'
                    '<td style="width:40mm;padding:0">'+artwork(decorative[0],40,40)+'</td></tr></table>')
            w,h=template_dimensions(templates[0]['local_template'])
            art=artwork(templates[0],w,h)
            if len(decorative)>1:
                art=('<table style="width:186mm;table-layout:fixed;border-collapse:collapse"><tr>'
                     +''.join('<td style="padding:0;text-align:center">'+artwork(a,40,40)+'</td>' for a in decorative)
                     +'</tr></table>'+art)
        else:
            side=math.ceil(math.sqrt(visual_area*1.03/len(images)))
            if len(images)==1:art=artwork(images[0],side,side)
            else:
                if len(images)>4:return
                rows=[]
                for i in range(0,len(images),2):
                    rows.append('<tr>'+''.join('<td style="padding:0">'+artwork(a,side,side)+'</td>' for a in images[i:i+2])+'</tr>')
                art='<table style="width:186mm;border-collapse:collapse">'+''.join(rows)+'</table>'
        result=deepcopy(page);result['exercise']=deepcopy(checked['exercise']);result['_inline_source_labels']=True
        # "Above" must not point at the current response sheet when the table
        # or drawing surface is now on the preceding reference sheet.
        for q in result['exercise']['questions']:
            old=q['prompt'];new=re.sub(r'\b(table|cards?|terms?|steps?|template|sources?|passage|illustration) above\b',
                r'\1 on the reference page',old,flags=re.I)
            q['prompt']=new
        # Compiled slot payloads are canonical and replaced on validation; use
        # empty question slots so no stale prefilled prompt survives the move.
        response_parser=CanonicalTextContainers({});response_parser.feed(''.join(responses));response_parser.close()
        def empty_questions(node):
            """Retain all response-area siblings while removing only redundant slot payloads."""
            if isinstance(node,str) or 'comment' in node:return
            if str(dict(node['attrs']).get('data-content','')).startswith('question_'):node['children']=[]
            else:
                for child in node['children']:empty_questions(child)
        for node in response_parser.root:empty_questions(node)
        response_html=''.join(literal_html(n) for n in response_parser.root)
        result['html']=('<div>'+header+''.join(references)+art+'</div>'
            '<div style="break-before:page"><h2 data-content="continuation_title" style="font-size:'+str(font+3)+'pt;color:#167E80;margin:0 0 3mm"></h2>'+response_html+'</div>')
        yield result
    except (ValueError,TypeError,KeyError,IndexError,ZeroDivisionError):return
