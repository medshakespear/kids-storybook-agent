"""Bind tasks requiring exact blank areas to deterministic printable work materials."""
import re
from core.content_binding import CanonicalTextContainers
from core.print_grid import literal_html

SUBJECTS={'skull':r'skull|calavera','butterfly':r'butterfl(?:y|ies)',
          'leaf':r'leaf|leaves','heart':r'heart','pumpkin':r'pumpkin'}


def required_template(exercise: dict, title: str = '') -> str | None:
    """Detect a student drawing dependency, excluding decorative art and observational tasks."""
    prompts=[q.get('prompt','') for q in exercise.get('questions',[]) if isinstance(q,dict)]
    task=' '.join([str(exercise.get('directions','')),*map(str,prompts)])
    subject_text=title+' '+task
    if (re.search(r'\b(?:complete|finish|mirror|copy|draw)\b',task,re.I)
            and re.search(r'\b(?:half|other side|opposite side)\b',task,re.I)):
        for subject,pattern in SUBJECTS.items():
            if re.search(r'\b(?:'+pattern+r')\b',subject_text,re.I):return subject+'_symmetry'
    if (re.search(r'\b(?:banner|papel picado|paper flag)\b',subject_text,re.I)
            and re.search(r'\b(?:design|draw|sketch|plan|create)\b',task,re.I)
            and re.search(r'\b(?:draw|sketch|cutouts?|cut-work|motifs?|symmetr\w*|fold|papel picado|paper flag)\b',subject_text,re.I)):
        return 'banner_plan'
    return None


def template_dimensions(kind: str) -> tuple[float,float]:
    """Reserve a full-width student surface rather than a thumbnail or an illustration frame."""
    if kind.endswith('_symmetry') and kind[:-9] in SUBJECTS:return 150,110
    if kind=='banner_plan':return 168,95.2
    return 150,150/1.8


def on_template_drawing(prompt: str) -> bool:
    """Recognize explicit drawing on a template, never separate writing or practice."""
    return isinstance(prompt,str) and bool(
        re.search(r'^On (?:the )?blank right (?:side|half) of (?:the )?\w+(?: \w+){0,2} template\b',prompt,re.I)
        and re.search(r'\b(?:mirror|copy|draw|complete)\b',prompt,re.I)
        and not re.search(r'\b(?:write|explain|paragraph|sentences?|space below|practice)\b',prompt,re.I))


def prepare_work_template(page: dict, config: dict, title: str = '') -> None:
    """Keep authored content/layout; route one unambiguous work asset away from image AI."""
    exercise=page.get('exercise')
    if isinstance(exercise,dict):
        for question in exercise.get('questions',[]):
            if isinstance(question,dict):question.pop('_template_response_asset',None)
    if (not config.get('student_workbook') or not isinstance(exercise,dict)
            or exercise.get('render_mode')!='authored'):return
    kind=required_template(exercise,title)
    if kind is None:return
    images=page.get('images')
    if not isinstance(images,list):return  # Normal manifest validation reports malformed drafts.
    subject=kind.removesuffix('_symmetry')
    pattern=SUBJECTS.get(subject,r'banner|papel picado|paper flag|template')
    candidates=[a for a in images if isinstance(a,dict) and isinstance(a.get('id'),str)
                and re.search(r'\b(?:'+pattern+r')\b',(a['id'].replace('_',' ')+' '+str(a.get('prompt',''))),re.I)]
    explicit=[a for a in candidates if re.search(r'\b(?:blank|template|outline|unfinished|half)\b',str(a.get('prompt','')),re.I)]
    chosen=explicit[0] if len(explicit)==1 else candidates[0] if len(candidates)==1 else None
    if chosen is None:
        if len(images)>=4:raise ValueError('Work template needs its own asset: retain a blank drawing template and at most three decorative illustrations')
        used={a.get('id') for a in images if isinstance(a,dict)}
        aid=next('work_template'+('_'+str(i) if i else '') for i in range(5) if 'work_template'+('_'+str(i) if i else '') not in used)
        chosen={'id':aid,'prompt':'Locally drawn student work template.'};images.append(chosen)
    chosen['local_template']=kind
    # Keep the original art brief for provenance; it is never sent to Cloudflare.
    page['work_template']={'kind':kind,'asset_id':chosen['id']}
    parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
    found=[];questions=[]

    def visit(children):
        """Read actual asset references and question anchors; preserve all other content."""
        for index,node in enumerate(children):
            if isinstance(node,str) or 'comment' in node:continue
            attrs=dict(node['attrs'])
            if node['tag']=='img' and attrs.get('data-asset')==chosen['id']:found.append(node)
            if str(attrs.get('data-content','')).startswith('question_'):questions.append((children,index))
            visit(node['children'])

    visit(parser.root)
    if not found and questions:
        children,index=questions[0]
        node={'tag':'img','attrs':[('data-asset',chosen['id'])],'children':[]}
        children.insert(index,node);found.append(node)
    width,height=template_dimensions(kind)
    for node in found:
        style=dict(node['attrs']).get('style','') or ''
        style=';'.join(d for d in style.split(';') if d.split(':',1)[0].strip().lower() not in
                       {'width','height','min-width','max-width','min-height','max-height','object-fit','object-position'})
        node['attrs']=[(k,v) for k,v in node['attrs'] if k!='style']+[
            ('style',style+f';width:{width:g}mm;height:{height:g}mm;object-fit:contain')]
    page['html']=''.join(literal_html(n) for n in parser.root)
    replacements={}
    for question in exercise.get('questions',[]):
        prompt=question.get('prompt','')
        if not isinstance(prompt,str):continue
        # A task explicitly performed ON the printed template already has a
        # response surface. Do not add another unrelated drawing rectangle.
        # Derive this marker locally; model-provided markers are cleared above.
        if kind.endswith('_symmetry') and on_template_drawing(prompt):
            question['_template_response_asset']=chosen['id']
        if kind.endswith('_symmetry') and re.search(r'\b(?:complete|finish)\b',prompt,re.I) and re.search(r'\bhalf\b',prompt,re.I):
            new=prompt
            if re.search(r'\b(?:complete|finish)\b[^.!?]{0,60}\bleft half\b',new,re.I):
                new=re.sub(r'\b(left|right)\b',lambda m:'right' if m[1].lower()=='left' else 'left',new,flags=re.I)
            new=re.sub(r'\b(?:blank\s+)?(?:uncolored|uncoloured|unfinished|missing|other|second|right)\s+half\b','blank right half',new,flags=re.I)
            if not re.search(r'\bdraw\b',new,re.I):new=new.rstrip()+' Draw directly on the template.'
            if new!=prompt:
                question['prompt']=new;replacements[prompt]=new
    if kind=='banner_plan':
        for question in exercise.get('questions',[]):
            prompt=question.get('prompt','')
            if isinstance(prompt,str) and re.search(r'\bin (?:the )?space below,?\s*draw\b',prompt,re.I):
                new=re.sub(r'\bin (?:the )?space below,?\s*draw\b','Draw',prompt,flags=re.I)
                new=re.sub(r'\bfor the banner\b','directly on the blank banner template',new,flags=re.I)
                if new!=prompt:
                    new+=' Use the space below for practice sketches.'
                    question['prompt']=new;replacements[prompt]=new
    # Model-written positional instructions must agree with the real work surface.
    fields=[(exercise,'directions')]+[(c,'text') for c in exercise.get('captions',[]) if isinstance(c,dict)]
    for record,key in fields:
        old=record.get(key)
        if kind=='banner_plan' and isinstance(old,str) and re.search(r'\b(?:box|template|workspace)\s+(?:above|below)\b',old,re.I):
            new='Use the large blank banner template on this page for your design.'
            record[key]=new;replacements[old]=new
    if replacements:
        literal=CanonicalTextContainers({});literal.feed(page['html']);literal.close()
        def replace_text(node):
            """Update only complete original printed wording, never attributes or source facts."""
            if isinstance(node,str):
                for old,new in replacements.items():node=node.replace(old,new)
                return node
            if 'children' in node:node['children']=[replace_text(c) for c in node['children']]
            return node
        page['html']=''.join(literal_html(replace_text(n)) for n in literal.root)


def check_template_geometry(document) -> None:
    """Measure the real printed image and reject small or letterboxed work surfaces."""
    for page in document.pages:
        for box in page._page_box.descendants():
            element=box.element
            kind=element.get('data-work-template') if element is not None else None
            if box.element_tag!='img' or not kind or not hasattr(box,'replacement'):continue
            if kind!='banner_plan' and not kind.endswith('_symmetry'):continue
            width,height=template_dimensions(kind)
            # Width and height are normalized to the template aspect ratio, so
            # a shallow frame cannot pass by leaving the actual drawing tiny.
            factor=min(box.width*25.4/96/width,box.height*25.4/96/height)
            if factor<0.99:
                raise ValueError(f'Design overflow: student work template is too small; reserve at least {width:g}mm by {height:g}mm for {kind}')


def template_layout_recovery(page: dict, minimum_font: int, visual_area: float):
    """Reflow one work template without omitting canonical content or independent writing panels."""
    images=page.get('images')
    if not page.get('_recovery_config',{}).get('student_workbook'):return
    if not isinstance(images,list) or len(images)!=1 or not images[0].get('local_template'):return
    yield from stacked_template_layout(page,minimum_font)
    yield from integrated_template_layout(page,minimum_font)
    from core.layout_recovery import single_illustration_recovery
    base=single_illustration_recovery(page,minimum_font,visual_area)
    if base is None:return
    width,height=template_dimensions(images[0]['local_template'])
    # Canonical questions already carry their full requested response areas.
    # Only decorative spacing is compacted; their dimensions stay unchanged.
    parser=CanonicalTextContainers({});parser.feed(base['html']);parser.close()
    def visit(node):
        """Set readable template geometry and normal-flow text without data-table flattening."""
        if isinstance(node,str) or 'comment' in node:return
        attrs=dict(node['attrs']);style=attrs.get('style','') or ''
        keep=';'.join(d for d in style.split(';') if not d.split(':',1)[0].strip().lower().startswith(('margin','padding')))
        if node['tag']=='img' and attrs.get('data-asset'):
            keep=';'.join(d for d in keep.split(';') if d.split(':',1)[0].strip().lower() not in {'width','height'})
            keep+=f';width:{width:g}mm;height:{height:g}mm;object-fit:contain'
        else:keep+=';margin:0 0 1mm;padding:0;line-height:1.15'
        node['attrs']=[(k,v) for k,v in node['attrs'] if k!='style']+[('style',keep)]
        for child in node['children']:visit(child)
    for node in parser.root:visit(node)
    base['html']=''.join(literal_html(n) for n in parser.root)
    yield base


def stacked_template_layout(page: dict, minimum_font: int):
    """Use full-width normal flow for a banner plus complete written responses."""
    from copy import deepcopy
    from core.page_contract import compile_exercise
    config=page.get('_recovery_config',{})
    if page['images'][0].get('local_template')!='banner_plan':return
    try:
        checked=deepcopy(page);blocks={}
        prepare_work_template(checked,config,page.get('_recovery_title','Banner studio'))
        compile_exercise(checked,config,page.get('_recovery_title','Banner studio'),blocks_out=blocks)
        if checked.get('_table_caption_ids'):return
        parser=CanonicalTextContainers({});parser.feed(checked['source_layout']);parser.close()
        if parser.stack:return
        seen=[];assets=[]
        def visit(node):
            """Reject independent prose, structured data and unnamed work surfaces."""
            if isinstance(node,str):
                if node.strip():raise ValueError('Keep literal text')
                return
            if 'comment' in node:raise ValueError('Keep comments')
            attrs=dict(node['attrs']);slot=attrs.get('data-content')
            if slot:seen.append(slot);return
            if node['tag']=='img':assets.append(attrs.get('data-asset'));return
            if node['tag'] in {'table','td','th','svg'}:raise ValueError('Keep data structure')
            if all(isinstance(c,str) and not c.strip() for c in node['children']) and re.search(r'(?:height|min-height|border)\s*:',attrs.get('style','')):
                raise ValueError('Keep independent working surface')
            for child in node['children']:visit(child)
        for node in parser.root:visit(node)
        asset=checked['images'][0]
        if assets!=[asset['id']] or len(seen)!=len(set(seen)) or not (set(blocks)-{'name','date'})<=set(seen):return
        exercise=checked['exercise']
        duplicate={'caption_'+c['id'] for c in exercise.get('captions',[]) if c['text']==exercise.get('directions')}
        exercise['captions']=[c for c in exercise.get('captions',[]) if 'caption_'+c['id'] not in duplicate]
        style=f'font-size:{minimum_font}pt;line-height:1.1;margin:0;padding:0'
        def slot_html(slot):
            """Preserve one canonical field in compact, readable normal flow."""
            return f'<div data-content="{slot}" style="{style};margin-bottom:0.6mm"></div>'
        header=f'<h1 data-content="title" style="font-size:{minimum_font+3}pt;color:#B33600;background-color:#FFF2DF;line-height:1.1;margin:0;padding:0.5mm"></h1>'
        header+=' '.join(f'<span data-content="{s}" style="{style}"></span>' for s in ('name','date') if s in seen)
        header+=slot_html('directions')
        width,height=template_dimensions(asset['local_template'])
        art=f'<img data-asset="{asset["id"]}" style="width:{width}mm;height:{height}mm;object-fit:contain;display:block;margin:0 auto"/>'
        supporting=[s for s in seen if s not in {'title','name','date','directions'}|duplicate and not s.startswith('question_')]
        result=deepcopy(page);result['exercise']=deepcopy(exercise);result['_inline_source_labels']=True
        result['html']=header+art+''.join(slot_html(s) for s in supporting)+''.join(slot_html('question_'+q['id']) for q in exercise['questions'])
        yield result
    except (ValueError,TypeError,KeyError,IndexError):return


def integrated_template_layout(page: dict, minimum_font: int):
    """Preserve on-template tasks, supporting text and extra blank practice panels.

    Source/guide text flows beside the actual 150mm template, not beside a
    thumbnail. Only explicitly on-template drawing responses are integrated.
    All other response boxes and independent work surfaces remain unchanged.
    """
    from copy import deepcopy
    from core.page_contract import compile_exercise
    config=page.get('_recovery_config',{})
    if not any(q.get('_template_response_asset') for q in page.get('exercise',{}).get('questions',[])):return
    try:
        checked=deepcopy(page);blocks={}
        # Retained diagnostic/retry sources carry the manifest and exercise,
        # not derived work_template metadata. Recompute it before compilation.
        prepare_work_template(checked,config,page.get('_recovery_title','Drawing studio'))
        compile_exercise(checked,config,page.get('_recovery_title','Drawing studio'),blocks_out=blocks)
        parser=CanonicalTextContainers({});parser.feed(checked['source_layout']);parser.close()
        if parser.stack or checked.get('_table_caption_ids'):return
        slots=[];panels=[];assets=[]

        def collect(node):
            """Retain only canonical text, the work asset and literal blank panels."""
            if isinstance(node,str):
                if node.strip():raise ValueError('Keep independent wording')
                return
            if 'comment' in node:raise ValueError('Keep comments')
            attrs=dict(node['attrs']);slot=attrs.get('data-content')
            if slot:slots.append(slot);return
            if node['tag']=='img':assets.append(attrs.get('data-asset'));return
            if all(isinstance(c,str) and not c.strip() for c in node['children']):
                if re.search(r'(?:height|min-height)\s*:\s*[1-9]',attrs.get('style','')):
                    panels.append(literal_html(node));return
            if node['tag'] in {'table','tr','td','th','svg'}:raise ValueError('Keep structured task relationships')
            for child in node['children']:collect(child)

        for node in parser.root:collect(node)
        if len(slots)!=len(set(slots)) or not (set(blocks)-{'name','date'})<=set(slots):return
        image=page['images'][0]
        if assets!=[image['id']]:return
        width,height=template_dimensions(image['local_template'])
        if width>150:return
        style=f'font-size:{minimum_font}pt;line-height:1.15;margin:0;padding:0'
        def container(slot):
            """Render exactly one canonical slot in normal print flow."""
            return f'<div data-content="{slot}" style="{style};margin-bottom:1mm"></div>'
        header=f'<h1 data-content="title" style="font-size:{minimum_font+3}pt;line-height:1.15;color:#8B3213;background-color:#FFF2DF;margin:0 0 1mm;padding:1mm"></h1>'
        header+=' '.join(f'<span data-content="{s}" style="{style}"></span>' for s in ('name','date') if s in slots)
        header+=container('directions')
        supporting=[s for s in slots if s not in {'title','name','date','directions'} and not s.startswith('question_')]
        body=(f'<table style="width:186mm;table-layout:fixed;border-collapse:collapse"><tr>'
              f'<td style="width:{width}mm;vertical-align:top;padding:0"><img data-asset="{image["id"]}" style="width:{width}mm;height:{height}mm;object-fit:contain"/></td>'
              '<td style="vertical-align:top;padding:0 0 0 1mm">'+''.join(container(s) for s in supporting)+'</td></tr></table>')
        tail=''.join(container('question_'+q['id']) for q in checked['exercise']['questions'])
        result=deepcopy(page);result['exercise']=deepcopy(checked['exercise'])
        result['html']=header+body+tail+''.join(panels)
        yield result
    except (ValueError,TypeError,KeyError,IndexError):return
