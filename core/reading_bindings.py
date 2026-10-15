"""Restore declared reading content and neutral source labels in student-authored layouts."""
from core.content_binding import CanonicalTextContainers,canonical_content_slot
from core.print_grid import literal_html

READING_HEADINGS={
    'context_reading':'Reading Context','reading_heading':'Reading',
    'passage_heading':'Reading','source_heading':'Source',
    'reading_title':'Reading','source_title':'Source',
}
FLOW_PARENTS={None,'div','section','td','li'}


def declare_reading_headings(markup: str, exercise: dict, config: dict) -> None:
    """Name only explicit empty reading-heading slots when canonical reading content exists.

    No source facts are generated. Existing captions and nonempty unknown slots
    remain untouched. A directly adjacent source may supply its own retained
    label, keeping the source heading and body consistently identified.
    """
    if not config.get('student_workbook') or not isinstance(exercise,dict) or exercise.get('render_mode')!='authored': return
    sources=exercise.get('stimuli',[])
    sources=sources if isinstance(sources,list) else []
    labels={}
    has_source=False
    for source in sources:
        if not isinstance(source,dict): continue
        if isinstance(source.get('text'),str) and source['text'].strip(): has_source=True
        if isinstance(source.get('id'),str) and isinstance(source.get('label'),str) and source['label'].strip():
            labels['stimulus_'+source['id']]=source['label'].strip()
    passage=exercise.get('passage')
    if not has_source and not (isinstance(passage,str) and passage.strip()): return
    captions=exercise.get('captions',[])
    if not isinstance(captions,list): return
    known={slot for c in captions if isinstance(c,dict) and isinstance(c.get('id'),str)
           for slot in (c['id'],'caption_'+c['id'])}
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack:return

    def visit(children, in_slot=False):
        """Use structural heading roles, never infer wording from an answer or illustration prompt."""
        peers=[c for c in children if not isinstance(c,str) or c.strip()]
        for index,node in enumerate(peers):
            if isinstance(node,str) or 'comment' in node:continue
            slot=dict(node['attrs']).get('data-content')
            cid=slot.removeprefix('caption_') if isinstance(slot,str) else ''
            empty=all(isinstance(c,str) and not c.strip() for c in node['children'])
            if (not in_slot and node['tag'] in {'h2','h3','h4','h5','h6','p','div','span'} and empty
                    and slot not in known and slot=='caption_'+cid and cid in READING_HEADINGS):
                text=READING_HEADINGS[cid]
                if cid.startswith('source_') and index+1<len(peers) and isinstance(peers[index+1],dict):
                    following=dict(peers[index+1].get('attrs',[])).get('data-content')
                    text=labels.get(following,text)
                if len(text)<=120:
                    captions.append({'id':cid,'text':text});known.add(slot)
            visit(node['children'],in_slot or bool(slot))

    visit(parser.root)
    if captions:exercise['captions']=captions


def restore_reading_slots(markup: str, blocks: dict, exercise: dict, config: dict) -> str | None:
    """Place omitted canonical reading text before questions without altering its wording.

    Input has already gone through whole-text binding, so a formatted existing
    passage is recognized before restoration. Non-reading captions, missing
    questions and data-table cells remain strict errors. Actual page geometry is
    still measured after insertion; oversized content is never truncated.
    """
    if not config.get('student_workbook') or exercise.get('render_mode')!='authored':return None
    parser=CanonicalTextContainers(blocks);parser.feed(markup);parser.close()
    if parser.stack:return None
    positions={};questions=[]

    def inspect(children, parent_tag=None, path=(), in_slot=False):
        """Retain safe insertion ancestors rather than placing block text in a table row or paragraph."""
        for index,node in enumerate(children):
            if isinstance(node,str) or 'comment' in node:continue
            slot=canonical_content_slot(dict(node['attrs']).get('data-content'),blocks)
            ancestry=path+((children,index,parent_tag),)
            if slot and not in_slot:
                positions.setdefault(slot,[]).append(ancestry)
                if slot.startswith('question_'):questions.append(ancestry)
            inspect(node['children'],node['tag'],ancestry,in_slot or bool(slot))

    inspect(parser.root)
    heading_slots=['caption_'+c['id'] for c in exercise.get('captions',[]) if isinstance(c,dict)
                   and c.get('id') in READING_HEADINGS and 'caption_'+c['id'] in blocks]
    missing_headings=[slot for slot in heading_slots if slot not in positions]
    missing_passage='passage' in blocks and 'passage' not in positions
    if not missing_headings and not missing_passage:return None

    def insertion(path, *, after=False):
        """Choose the nearest normal-flow ancestor and preserve every existing node."""
        for children,index,parent_tag in reversed(path):
            if parent_tag in FLOW_PARENTS:return children,index+(1 if after else 0)
        return None

    anchor=None
    if not missing_passage and len(positions.get('passage',[]))==1:
        anchor=insertion(positions['passage'][0])
    elif missing_passage:
        retained=[p for slot in heading_slots for p in positions.get(slot,[])]
        if len(retained)==1:anchor=insertion(retained[0],after=True)
    if anchor is None and 'passage' not in blocks:
        sources=[p for slot,places in positions.items() if slot.startswith('stimulus_') for p in places]
        if len(sources)==1:anchor=insertion(sources[0])
    if anchor is None and questions:anchor=insertion(questions[0])
    if anchor is None:return None
    font=config.get('minimum_text_pt',12)
    additions=[]
    for slot in missing_headings+(['passage'] if missing_passage else []):
        heading=slot.startswith('caption_')
        style=f'font-size:{font}pt;line-height:1.2;margin:0 0 2mm'
        if heading:style+=';font-weight:bold'
        additions.append({'tag':'p' if heading else 'div','attrs':[('data-content',slot),('style',style)],'children':[]})
    children,index=anchor;children[index:index]=additions
    return ''.join(literal_html(node) for node in parser.root)
