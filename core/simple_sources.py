"""Lossless source cleanup for simple written exercises, before content binding."""
import re

from core.content_binding import CanonicalTextContainers
from core.print_grid import literal_html


def normalized(value: str) -> str:
    """Compare complete text independent of whitespace, without paraphrasing evidence."""
    return ' '.join(value.split()).casefold()


def remove_orphan_separators(markup: str, config: dict) -> str:
    """Remove isolated layout pipes, retaining source/table/task punctuation and work areas."""
    if not config.get('simple_exercises_only'):return markup
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    def visit(children, protected=False):
        """Never remove a character from a canonical field or from a real table."""
        prose=any(isinstance(c,str) and re.search(r'\w',c) for c in children)
        result=[]
        for node in children:
            if isinstance(node,str):
                if not protected and not prose and node.strip()=='|':continue
            elif 'comment' not in node:
                own=protected or node['tag']=='table' or bool(dict(node['attrs']).get('data-content'))
                node['children']=visit(node['children'],own)
            result.append(node)
        return result
    return ''.join(literal_html(n) for n in visit(parser.root))


def collapse_repeated_cards(text: str) -> str:
    """Keep one of two identical complete lettered lists, never merge different cards."""
    markers=list(re.finditer(r'(?<!\w)(?:Card\s+)?([A-H])[:.)]\s+',text))
    if len(markers)<4 or len(markers)%2:return text
    half=len(markers)//2
    labels=[m[1] for m in markers]
    if len(set(labels[:half]))!=half or labels[:half]!=labels[half:]:return text
    bodies=[text[m.end():markers[i+1].start() if i+1<len(markers) else len(text)].strip()
            for i,m in enumerate(markers)]
    if any(not a or normalized(a)!=normalized(b) for a,b in zip(bodies[:half],bodies[half:])):return text
    return text[:markers[0].start()]+text[markers[half].start():]


def normalize_student_header(markup: str, config: dict) -> str:
    """Move pure standard name/date slots into one full-width, readable header row."""
    if not config.get('simple_exercises_only'):return markup
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack:return markup
    places=[]

    def visit(children):
        """Find identifiers without crossing another canonical content container."""
        for node in children:
            if isinstance(node,str) or 'comment' in node:continue
            slot=dict(node['attrs']).get('data-content')
            if slot in {'name','date'}:places.append((children,node,slot))
            elif not slot:visit(node['children'])

    header=('<table style="width:175mm;table-layout:fixed;margin:1mm 0 2mm">'
        '<tr><td style="width:100mm;padding:0;vertical-align:top">'
        '<p data-content="name" style="margin:0;font-size:12pt"></p></td>'
        '<td style="width:75mm;padding:0;vertical-align:top">'
        '<p data-content="date" style="margin:0;font-size:12pt"></p></td></tr></table>')
    header_parser=CanonicalTextContainers({});header_parser.feed(header);header_parser.close()
    header=''.join(literal_html(n) for n in header_parser.root)
    visit(parser.root)
    if len(places)==2 and header in markup:return markup
    for _,node,slot in places:
        pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in node['children']]
        if any(p is None for p in pieces):return markup
        value=''.join(pieces).strip()
        if value and not re.fullmatch(slot+r'\s*:\s*[_\s]*',value,re.I):return markup
    for children,node,_ in places:children.remove(node)
    target=parser.root
    from core.continuation_layout import continuation_boundaries
    if continuation_boundaries(markup):
        roots=[n for n in parser.root if isinstance(n,dict) and 'comment' not in n]
        if len(roots)==2 and all(n['tag']=='div' for n in roots):target=roots[0]['children']
    index=next((i+1 for i,n in enumerate(target) if isinstance(n,dict)
                and dict(n.get('attrs',[])).get('data-content')=='title'),0)
    target[index:index]=header_parser.root
    return ''.join(literal_html(n) for n in parser.root)


def source_body(source: dict) -> str:
    """Ignore a repeated structural label only when comparing complete source bodies."""
    text=source.get('text','');label=source.get('label','')
    if not isinstance(text,str) or not isinstance(label,str) or not label.strip():return text
    if text.casefold().startswith(label.casefold()+':'):return text[len(label)+1:].lstrip()
    if re.fullmatch(r'(?:source|card|lab note|reading source|library text|card text|leader bio)(?:\s+[A-Z0-9])?',label,re.I):
        return re.sub(r'^'+re.escape(label)+r'\s+(?=[A-Z])','',text,count=1)
    return text


def prepare_simple_sources(page: dict, exercise: dict, config: dict) -> None:
    """Remove only exact redundant source copies and their redundant metadata labels.

    Differing accounts, explicitly referenced identities, comparison pairs, media,
    handwriting surfaces and partial source copies remain untouched. Source facts
    and all answers are retained. No factual text is generated from an ID.
    """
    if not config.get('simple_exercises_only') or exercise.get('render_mode')!='authored':return
    from core.activity_stimuli import normalize_stimulus_ids
    normalize_stimulus_ids(page,exercise)
    sources=exercise.get('stimuli',[]);captions=exercise.get('captions',[])
    if not isinstance(sources,list) or not isinstance(captions,list):return
    # Consolidate only a complete same-letter, same-body list repeated inside
    # one source, synchronizing literal prefills for canonical binding.
    for source in sources:
        if isinstance(source,dict) and isinstance(source.get('text'),str):
            old=source['text'];new=collapse_repeated_cards(old)
            if new!=old:
                source['text']=new
                from html import escape
                page['html']=page['html'].replace(escape(old),escape(new))
    parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
    if parser.stack:return
    positions={}

    def locate(children, in_table=False):
        """Track real content containers without crossing an existing content owner."""
        for node in children:
            if isinstance(node,str) or 'comment' in node:continue
            markup=literal_html(node) if node['tag']=='table' else ''
            table=in_table or (node['tag']=='table' and
                (bool(re.search(r'<th\b',markup)) or len(re.findall(r'<tr\b',markup))>1))
            slot=dict(node['attrs']).get('data-content')
            if slot:positions.setdefault(slot,[]).append((children,node,table))
            else:locate(node['children'],table)

    locate(parser.root)
    questions=exercise.get('questions',[])
    task=' '.join([str(exercise.get('directions',''))]+[str(q.get('prompt','')) for q in questions if isinstance(q,dict)])
    compare=bool(re.search(r'\b(?:both sources|two (?:sources|accounts|passages)|each source|compare)\b',task,re.I))
    changed=False

    def remove_slot(slot, text, label=''):
        """Remove only an empty slot or a complete formatted copy of its canonical text."""
        places=positions.get(slot,[])
        if len(places)>1:return False
        for children,node,in_table in places:
            if slot.startswith('caption_') and (in_table or node['tag'] in {'td','th'}):return False
            pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in node['children']]
            if any(p is None for p in pieces):return False
            printed=normalized(''.join(pieces))
            expected={normalized(text),normalized(label+' '+text),normalized(label+': '+text)}
            if printed and printed not in expected:return False
        for children,node,_ in places:children.remove(node)
        positions.pop(slot,None)
        return True

    from core.workbook_tasks import repeated_inventory_sources
    table_copies=repeated_inventory_sources(page,exercise)
    kept=[];seen={};removed_labels=[]
    passage=exercise.get('passage')
    if isinstance(passage,str) and passage.strip():seen[normalized(passage)]='passage'
    for source in sources:
        if not isinstance(source,dict) or not isinstance(source.get('id'),str) or not isinstance(source.get('text'),str):
            kept.append(source);continue
        sid=source['id'];text=source['text'];label=source.get('label','')
        label=label if isinstance(label,str) else ''
        referenced=bool(label.strip() and normalized(label) in normalized(task))
        duplicate=normalized(source_body(source)) in seen or sid in table_copies
        comparing_sources=bool(re.search(r'\b(?:both sources|two (?:sources|accounts|passages)|each source|compare.{0,30}(?:sources|accounts|passages))\b',task,re.I))
        table_copy=sid in table_copies and not comparing_sources
        if (duplicate and not referenced and (not compare or table_copy)
                and remove_slot('stimulus_'+sid,text,label)):
            removed_labels.append(label);changed=True;continue
        seen.setdefault(normalized(source_body(source)),'stimulus_'+sid);kept.append(source)
    if changed:exercise['stimuli']=kept

    # An answer-bearing summary used as a source heading is already present in
    # the source body. Give the card a neutral label, not a repeated answer.
    for index,source in enumerate(kept,1):
        if not isinstance(source,dict) or not isinstance(source.get('text'),str):continue
        label=source.get('label');body=source['text']
        if isinstance(label,str) and len(label.split())>=8:
            bare=re.sub(r'^(?:reading\s+)?source\s*:\s*','',label,flags=re.I).strip()
            if normalized(bare) in normalized(body) and normalized(label) not in normalized(task):
                source['label']='Reading Source' if len(kept)==1 else f'Source {index}'
                changed=True

    bodies=[s['text'] for s in kept if isinstance(s,dict) and isinstance(s.get('text'),str)]
    if isinstance(passage,str) and passage.strip():bodies.append(passage)
    retained=[]
    for caption in captions:
        if not isinstance(caption,dict) or not isinstance(caption.get('text'),str) or not isinstance(caption.get('id'),str):
            retained.append(caption);continue
        cid=caption['id'];text=caption['text'];bare=re.sub(r'^(?:reading\s+)?source\s*:\s*','',text,flags=re.I).strip()
        redundant=(len(bare.split())>=8 and any(normalized(bare) in normalized(b) for b in bodies)
                   and bool(re.search(r'(?:source|label|heading|bio|card|text)',cid)))
        redundant=redundant or (bool(text.strip()) and any(normalized(text)==normalized(v) for v in removed_labels))
        for source in kept:
            if not isinstance(source,dict) or normalized(str(source.get('label','')))!=normalized(text):continue
            own=positions.get('caption_'+cid,[]);following=positions.get('stimulus_'+str(source.get('id')),[])
            if len(own)==len(following)==1 and own[0][0] is following[0][0]:
                peers=[n for n in own[0][0] if not isinstance(n,str) or n.strip()]
                adjacent=peers.index(following[0][1])==peers.index(own[0][1])+1
                redundant=redundant or adjacent
        if redundant and normalized(text) not in normalized(task) and remove_slot('caption_'+cid,text):
            changed=True;continue
        retained.append(caption)
    if len(retained)!=len(captions):exercise['captions']=retained
    if changed:page['html']=''.join(literal_html(n) for n in parser.root)


def neutralize_layout_references(page: dict, exercise: dict, config: dict) -> None:
    """Keep wording correct when source/table placement changes during safe reflow."""
    if not config.get('simple_exercises_only'):return
    source_text=' '.join([str(exercise.get('passage',''))]+[str(s.get('text','')) for s in exercise.get('stimuli',[]) if isinstance(s,dict)])
    has_sources=bool(source_text.strip())
    has_table=bool(re.search(r'<th\b',page['html'],re.I) or len(re.findall(r'<tr\b',page['html'],re.I))>1)
    records=[(exercise,'directions')]+[(q,'prompt') for q in exercise.get('questions',[]) if isinstance(q,dict)]
    replacements={}
    for record,key in records:
        old=record.get(key)
        if not isinstance(old,str):continue
        new=old
        nouns=[]
        if has_sources:nouns.extend(['source sentences','source cards','source texts','source text','reading passage','sources','passages','sentences','notes','records','source','passage'])
        if has_table:nouns.extend(['data table','table','chart','timetable'])
        if nouns:
            pattern=r'\b('+ '|'.join(nouns)+r')\s+(?:(?:shown|printed)\s+)?(?:above|below|on (?:the )?(?:left|right))\b'
            new=re.sub(pattern,lambda m:m[1]+' provided',new,flags=re.I)
        target=re.search(r'\bunderlined word\s+[\x27\"‘“]([^\x27\"’”]+)[\x27\"’”]',new,re.I)
        if target and re.search(r'(?<!\w)'+re.escape(target[1])+r'(?!\w)',source_text,re.I):
            new=re.sub(r'\bunderlined word\b','word',new,flags=re.I)
        if new!=old:record[key]=new;replacements[old]=new
    if not replacements:return
    parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
    def replace(node):
        """Synchronize complete prefilled text, preserving all other markup and content."""
        if isinstance(node,str):
            for old,new in replacements.items():node=node.replace(old,new)
            return node
        if 'children' in node:node['children']=[replace(c) for c in node['children']]
        return node
    page['html']=''.join(literal_html(replace(n)) for n in parser.root)
