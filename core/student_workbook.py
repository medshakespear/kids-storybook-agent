"""Student-facing content and handwriting contracts for contextual varied workbooks."""
import html
import math
import re


def consolidate_response_panels(markup: str, questions: list, config: dict) -> str:
    """Absorb a redundant adjacent blank box into its larger canonical answer box.

    Student questions already print their requested writing area. Only a single,
    empty, plain bordered sibling whose explicit height is no larger than that area
    is redundant. Named panels, media, wording, groups of work panels, oversized
    panels and legacy pages remain untouched.
    """
    if not config.get('student_workbook'): return markup
    from core.content_binding import CanonicalTextContainers
    from core.print_grid import literal_html
    import tinycss2
    from tinycss2.color3 import parse_color
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack: return markup
    heights={'question_'+str(q.get('id')):q.get('space_mm',0) for q in questions}
    prompts={'question_'+str(q.get('id')):str(q.get('prompt','')) for q in questions}
    changed=False

    def panel_height(node, *, allow_paper_tint=False):
        """Recognize only a style-only empty rectangle with explicit millimeter height."""
        if not isinstance(node,dict) or node.get('tag')!='div': return None
        if len(node['attrs'])!=1 or node['attrs'][0][0]!='style': return None
        if any(not isinstance(c,str) or c.strip() for c in node['children']): return None
        declarations=tinycss2.parse_declaration_list(node['attrs'][0][1],skip_comments=True,skip_whitespace=True)
        allowed={'height','min-height','border','border-radius','margin','margin-top','margin-bottom','margin-left','margin-right',
                 'background','background-color','padding','padding-top','padding-bottom','padding-left','padding-right','box-sizing'}
        values={}
        for d in declarations:
            if d.type!='declaration' or d.lower_name not in allowed or d.important: return None
            if d.lower_name in values: return None
            values[d.lower_name]=tinycss2.serialize(d.value).strip()
        # Paper-white and nearly white stationery fills do not define another
        # task. Tinted panels qualify only when the prompt does not reference
        # their color/shape; keep strong colors and transparency as authored work.
        for key in ('background','background-color'):
            if key not in values:continue
            color=parse_color(values[key])
            paper_tint=(allow_paper_tint and isinstance(color,tuple) and len(color)==4
                        and color[3]==1 and min(color[:3])>=250/255)
            if color!=(1,1,1,1) and not paper_tint:return None
        if not re.search(r'\b(?:solid|dashed|dotted)\b',values.get('border','')): return None
        def length(value):
            """Measure fixed CSS units without accepting relative or negative sizes."""
            if value=='0':return 0
            match=re.fullmatch(r'(\d+(?:\.\d+)?|\.\d+)(mm|px|pt|cm|in)',value)
            return float(match[1])*{'mm':1,'px':25.4/96,'pt':25.4/72,'cm':10,'in':25.4}[match[2]] if match else None
        sizes=[]
        for key in ('height','min-height'):
            if key in values:
                size=length(values[key])
                if size is None:return None
                sizes.append(size)
        padding=[length(v) for v in values.get('padding','0').split()]
        if len(padding) not in (1,2,3,4) or None in padding:return None
        top=padding[0];bottom=padding[0] if len(padding)<3 else padding[2]
        top=length(values.get('padding-top',f'{top}mm'));bottom=length(values.get('padding-bottom',f'{bottom}mm'))
        if top is None or bottom is None:return None
        if values.get('box-sizing','content-box') not in {'border-box','content-box'}:return None
        inset=0 if values.get('box-sizing')=='border-box' else top+bottom
        return max(sizes)+inset if sizes and min(sizes)>0 else None

    def visit(children):
        """Consolidate direct siblings only; never move or infer an independent task."""
        nonlocal changed
        for node in children:
            if isinstance(node,dict) and 'children' in node: visit(node['children'])
        indices=[i for i,n in enumerate(children) if not isinstance(n,str) or n.strip()]
        removals=[]
        for offset,index in enumerate(indices[:-1]):
            node=children[index]
            if not isinstance(node,dict) or 'attrs' not in node: continue
            slot=dict(node['attrs']).get('data-content')
            height=heights.get(slot,0)
            tinted=not re.search(r'\b(?:colou?r(?:ed|ful|ing|s)?|pink|red|blue|green|yellow|purple|orange|shades?|tints?|backgrounds?|box(?:es)?|panels?|rectangles?)\b',prompts.get(slot,''),re.I)
            next_index=indices[offset+1];size=panel_height(children[next_index],allow_paper_tint=tinted)
            if not size or size>height: continue
            # Multiple adjacent surfaces can be intentional multi-part work.
            if offset+2<len(indices) and panel_height(children[indices[offset+2]],allow_paper_tint=tinted) is not None: continue
            removals.append(next_index)
        for index in reversed(removals): del children[index];changed=True

    visit(parser.root)
    return ''.join(literal_html(n) for n in parser.root) if changed else markup


def check_activity(exercise: dict, config: dict) -> None:
    """Keep varied grades 3-6 focused on contextual tasks rather than geometric fillers."""
    if not config.get('student_workbook'): return
    if exercise.get('render_mode')!='authored' or exercise.get('mechanic')=='statement_path':
        raise ValueError('Student workbook needs a contextual authored activity: re-author this brief '
            'as evidence sorting, text matching, editing, data interpretation or another direct '
            'grade-appropriate task. Do not substitute shape puzzles or checkpoint mazes.')
    values=[exercise.get('passage',''),exercise.get('directions','')]
    values.extend(s.get('text','') for s in exercise.get('stimuli',[]) if isinstance(s,dict))
    for value in values:
        if isinstance(value,str) and re.search(r'\bbarometer\s+(?:recorded|measured)\s+(?:(?:a|the|total|heavy|daily)\s+){0,4}(?:rainfall|rain|precipitation)\b',value,re.I):
            raise ValueError('Workbook content: a rain gauge measures rainfall; a barometer measures '
                'air pressure. Correct the source and all dependent questions/answers together.')


def response_height(question: dict, config: dict) -> float:
    """Raise writing-space floors without ever reducing an explicitly larger workspace."""
    supplied=question.get('space_mm',0)
    if type(supplied) not in {int,float} or not math.isfinite(supplied) or not 0<=supplied<=80:
        raise ValueError('Exercise response space_mm must be 0-80; keep drawing/writing space usable')
    if not config.get('student_workbook'): return supplied
    prompt=question.get('prompt','')
    extended=bool(re.search(r'\b(?:paragraph|draft|rewrite|revise|design|draw|sketch|plan|two reasons|two statements|two sentences)\b',prompt,re.I))
    floor=config.get('extended_response_mm',50) if extended else config.get('minimum_response_mm',35)
    height=max(supplied,floor)
    question['space_mm']=height
    return height


def response_box(question: dict, height: float, config: dict) -> str:
    """Draw full-height writing boxes with subtle handwriting lines; keep drawing areas blank."""
    if config.get('student_workbook') and question.get('_template_response_asset'):return ''
    if not height: return ''
    lines=''
    drawing=(not config.get('simple_exercises_only') and
             re.search(r'\b(?:draw|sketch|illustrate|diagram|poster|collage)\b',question.get('prompt',''),re.I))
    if config.get('student_workbook') and not drawing:
        lines=''.join('<span style="display:block;height:8mm;border-bottom:0.2mm solid #CCD7DF;margin:0 2mm"></span>'
            for _ in range(max(0,int((height-4)//8))))
    return f'<span style="display:block;height:{height:g}mm;border:0.4mm solid #809AA6;margin-top:3mm;border-radius:3mm">{lines}</span>'


def adjacent_source_labels(markup: str, sources: list, captions: list, config: dict) -> set:
    """Find a source label already printed in its immediately preceding caption slot.

    Only direct siblings with matching canonical wording qualify. A label on a
    different card or in a separate column cannot suppress a source's own label.
    Both content slots and all shared source/caption fields remain required.
    """
    if not config.get('student_workbook'): return set()
    from core.content_binding import CanonicalTextContainers
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack: return set()
    labels={}
    for source in sources:
        label=source.get('label') if isinstance(source,dict) else None
        if isinstance(label,str) and label.strip() and isinstance(source.get('id'),str):
            labels['stimulus_'+source['id']]=' '.join(label.split()).casefold()
    caption_labels={'caption_'+c['id']:' '.join(c['text'].split()).casefold()
        for c in (captions if isinstance(captions,list) else []) if isinstance(c,dict) and isinstance(c.get('id'),str)
        and isinstance(c.get('text'),str)}
    found=set()

    def wrapped_slot(node):
        """Look through a single formatting wrapper, never across cards or columns."""
        if not isinstance(node,dict):return None
        slot=dict(node.get('attrs',[])).get('data-content')
        if slot:return slot
        if node.get('tag') not in {'h1','h2','h3','h4','h5','h6','p','span','strong','b','em'}:
            return None
        children=[c for c in node.get('children',[]) if not isinstance(c,str) or c.strip()]
        return wrapped_slot(children[0]) if len(children)==1 else None

    def visit(children):
        """Inspect adjacent bound containers without interpreting unbound model wording."""
        peers=[c for c in children if not isinstance(c,str) or c.strip()]
        for previous,current in zip(peers,peers[1:]):
            if not isinstance(previous,dict) or not isinstance(current,dict): continue
            before=wrapped_slot(previous)
            after=dict(current.get('attrs',[])).get('data-content')
            if after in labels and caption_labels.get(before)==labels[after]:
                found.add(after.removeprefix('stimulus_'))
        for child in children:
            if isinstance(child,dict) and 'children' in child: visit(child['children'])

    visit(parser.root)
    return found


def source_markup(source: dict, text: str, config: dict, *, external_label: bool = False, inline_label: bool = False) -> str:
    """Print a source label once, using its own prefix or an already-adjacent bound caption."""
    if not config.get('student_workbook'): return html.escape(text)
    label=source.get('label')
    if not isinstance(label,str) or not label.strip():
        prefix=text.split(':',1)[0]
        label=prefix if ':' in text and len(prefix)<=48 else source['id'].replace('_',' ').title()
    label=' '.join(label.split())[:48]
    source['label']=label
    body=text
    if text.casefold().startswith(label.casefold()+':'):
        body=text[len(label)+1:].lstrip()
    elif config.get('simple_exercises_only') and re.fullmatch(
            r'(?:source|card|lab note|reading source|library text|card text|leader bio)(?:\s+[A-Z0-9])?',label,re.I):
        body=re.sub(r'^'+re.escape(label)+r'\s+(?=[A-Z])','',text,count=1)
    if external_label: return html.escape(body)
    return '<strong>'+html.escape(label)+'</strong>'+(' ' if inline_label else '<br/>')+html.escape(body)


def check_response_width(document, profile: dict) -> None:
    """Measure actual answer-box widths so a tall but narrow side column cannot pass."""
    minimum=profile.get('minimum_response_width_mm',0)
    if not minimum: return
    seen=set()
    for page in document.pages:
        for box in page._page_box.descendants():
            element=getattr(box,'element',None)
            style=element.get('style','') if element is not None else ''
            if (box.element_tag=='span' and 'solid #809AA6' in style
                    and id(element) not in seen):
                seen.add(id(element));width=box.width*25.4/96
                if width+0.5<minimum:
                    raise ValueError(f'Design overflow: student answer box is only {width:.1f}mm wide; '
                        f'use at least {minimum}mm. Place questions below the illustration/source '
                        'region, preserving the full response heights and readable text.')


def check_data_table_width(document, profile: dict) -> None:
    """Keep four-or-more-column data tables out of cramped illustration side columns."""
    minimum=profile.get('minimum_data_table_width_mm',0)
    if not minimum:return
    for page in document.pages:
        for box in page._page_box.descendants():
            if type(box).__name__!='TableBox' or box.element is None:continue
            element=box.element;rows=[]
            for child in element:
                if child.tag=='tr':rows.append(child)
                elif child.tag in {'thead','tbody','tfoot'}:rows.extend(c for c in child if c.tag=='tr')
            if len(rows)<2:continue
            cells=[c for c in rows[0] if c.tag in {'td','th'}]
            if len(cells)<4 or not any(c.tag=='th' for c in cells):continue
            width=box.width*25.4/96
            if width+0.5<minimum:
                raise ValueError(f'Design overflow: data table with {len(cells)} columns is only {width:.1f}mm wide; '
                    f'use at least {minimum}mm. Place the complete table below the illustration rather than '
                    'squeezing its headers into a narrow side column. Retain every value and answer area.')
