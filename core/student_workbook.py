"""Student-facing content and handwriting contracts for contextual varied workbooks."""
import html
import math
import re


def consolidate_response_panels(markup: str, questions: list, config: dict) -> str:
    """Absorb a redundant adjacent blank box into its larger canonical answer box.

    Student questions already print their requested writing area. Only a single,
    empty, border-only sibling whose explicit height is no larger than that area
    is redundant. Named panels, media, wording, groups of work panels, oversized
    panels and legacy pages remain untouched.
    """
    if not config.get('student_workbook'): return markup
    from core.content_binding import CanonicalTextContainers
    from core.print_grid import literal_html
    import tinycss2
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack: return markup
    heights={'question_'+str(q.get('id')):q.get('space_mm',0) for q in questions}
    changed=False

    def panel_height(node):
        """Recognize only a style-only empty rectangle with explicit millimeter height."""
        if not isinstance(node,dict) or node.get('tag')!='div': return None
        if len(node['attrs'])!=1 or node['attrs'][0][0]!='style': return None
        if any(not isinstance(c,str) or c.strip() for c in node['children']): return None
        declarations=tinycss2.parse_declaration_list(node['attrs'][0][1],skip_comments=True,skip_whitespace=True)
        allowed={'height','min-height','border','border-radius','margin','margin-top','margin-bottom','margin-left','margin-right'}
        values={}
        for d in declarations:
            if d.type!='declaration' or d.lower_name not in allowed or d.important: return None
            if d.lower_name in values: return None
            values[d.lower_name]=tinycss2.serialize(d.value).strip()
        if not re.search(r'\b(?:solid|dashed|dotted)\b',values.get('border','')): return None
        sizes=[]
        for key in ('height','min-height'):
            if key in values:
                match=re.fullmatch(r'(\d+(?:\.\d+)?)mm',values[key])
                if not match: return None
                sizes.append(float(match[1]))
        return max(sizes) if sizes and min(sizes)>0 else None

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
            height=heights.get(dict(node['attrs']).get('data-content'),0)
            next_index=indices[offset+1];size=panel_height(children[next_index])
            if not size or size>height: continue
            # Multiple adjacent surfaces can be intentional multi-part work.
            if offset+2<len(indices) and panel_height(children[indices[offset+2]]) is not None: continue
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
    if not height: return ''
    lines=''
    drawing=re.search(r'\b(?:draw|sketch|illustrate|diagram|poster|collage)\b',question.get('prompt',''),re.I)
    if config.get('student_workbook') and not drawing:
        lines=''.join('<span style="display:block;height:8mm;border-bottom:0.2mm solid #CCD7DF;margin:0 2mm"></span>'
            for _ in range(max(0,int((height-4)//8))))
    return f'<span style="display:block;height:{height:g}mm;border:0.4mm solid #809AA6;margin-top:3mm;border-radius:3mm">{lines}</span>'


def source_markup(source: dict, text: str, config: dict) -> str:
    """Keep a source label and complete wording in one bound container, never separate cells."""
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
    return '<strong>'+html.escape(label)+'</strong><br/>'+html.escape(body)


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
