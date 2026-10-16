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


def prepare_work_template(page: dict, config: dict, title: str = '') -> None:
    """Keep authored content/layout; route one unambiguous work asset away from image AI."""
    exercise=page.get('exercise')
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
