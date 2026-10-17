"""Recover declared labels at unambiguous metadata or illustration anchors."""
import re
from core.content_binding import CanonicalTextContainers, canonical_content_slot
from core.print_grid import literal_html


def restore_declared_labels(markup: str, blocks: dict, exercise: dict, config: dict) -> str:
    """Restore retained captions without inventing wording or guessing diagram associations."""
    if not config.get('student_workbook') or exercise.get('render_mode') != 'authored':
        return markup
    parser = CanonicalTextContainers(blocks)
    parser.feed(markup)
    parser.close()
    used = set()
    assets = []
    containers = []
    metadata = {}
    source_anchors = {}

    def visit(children, inside=False, parent_tag=None):
        """Record only anchors outside canonical text slots."""
        for node in children:
            if isinstance(node, str) or 'comment' in node:
                continue
            attrs = dict(node['attrs'])
            slot = canonical_content_slot(attrs.get('data-content'), blocks)
            if slot:
                used.add(slot)
                if not inside and parent_tag in {None,'div','section','td','li'}:
                    source_anchors.setdefault(slot,[]).append((children,node))
                if slot in {'name','date'} and not inside:
                    metadata.setdefault(slot, []).append(node)
            if not inside and not slot:
                if node['tag'] == 'img' and attrs.get('data-asset') and parent_tag in {None,'div','section','td','li'}:
                    assets.append((children, node, attrs['data-asset']))
                pieces = [parser.plain_text(c) for c in node['children']]
                if all(p is not None for p in pieces):
                    containers.append((node, ' '.join(''.join(pieces).split()).casefold()))
            visit(node['children'], inside or bool(slot), node['tag'])

    visit(parser.root)
    for caption in exercise.get('captions', []):
        slot = 'caption_' + caption['id']
        if slot in used or slot not in blocks:
            continue
        text = ' '.join(caption['text'].split()).casefold()
        # A complete printed label is stronger evidence than its generated ID.
        matches = [node for node, value in containers if value and value == text]
        if len(matches) == 1:
            matches[0]['attrs'].append(('data-content', slot))
            matches[0]['children'] = []
            used.add(slot)
            continue
        cid = caption['id']
        anchor = None
        if cid in {'date_label', 'event_label', 'name_label'} and re.fullmatch(
                r'(?:date|event|name)\s*:\s*[_\s]*', text):
            # Reuse a blank built-in field instead of printing Date/Name twice.
            field = cid.removesuffix('_label')
            if len(metadata.get(field, [])) == 1:
                node = metadata[field][0]
                pieces = [parser.plain_text(c) for c in node['children']]
                own = ''.join(p for p in pieces if p is not None).strip()
                if all(p is not None for p in pieces) and (not own or re.fullmatch(
                        field + r'\s*:\s*[_\s]*', own, re.I)):
                    node['attrs'] = [(k, slot if k == 'data-content' else v) for k,v in node['attrs']]
                    node['children'] = []
                    used.add(slot)
                    continue
            # Identification labels have no inferred factual value.
            anchor = (parser.root, 0)
        elif cid.endswith('_label'):
            subject = cid[:-6]
            sources = source_anchors.get('stimulus_'+subject, [])
            if not sources and subject.endswith('_paragraph'):
                sources = source_anchors.get('passage', [])
            if not sources and subject in {'source','reading','passage'}:
                readings=[anchor for key,anchors in source_anchors.items()
                          if key=='passage' or key.startswith('stimulus_') for anchor in anchors]
                if len(readings)==1:sources=readings
            if len(sources)==1:
                children,node=sources[0]
                anchor=(children,children.index(node))
            candidates = [(children, node) for children, node, asset in assets
                          if subject and subject in re.split(r'[_-]', asset)]
            if anchor is None and len(candidates) == 1:
                children, node = candidates[0]
                anchor = (children, children.index(node) + 1)
        if anchor is not None:
            children, index = anchor
            children.insert(index, {'tag': 'p', 'attrs': [('data-content', slot),
                ('style', f"font-size:{config.get('minimum_text_pt',12)}pt;line-height:1.2;margin:0 0 2mm")], 'children': []})
            used.add(slot)
    return ''.join(literal_html(node) for node in parser.root)


def restore_declared_card_group(markup: str, blocks: dict, exercise: dict, config: dict) -> str:
    """Restore a complete omitted c1..cN text-card group before the student questions.

    Only simple written workbooks qualify. Retain every existing caption verbatim;
    never infer diagram labels, missing text, categories, answers or new tasks.
    Partial groups and short unattached labels still need an explicit layout repair.
    """
    if not config.get('simple_exercises_only') or exercise.get('render_mode')!='authored':return markup
    captions=exercise.get('captions',[])
    if not isinstance(captions,list):return markup
    cards=[c for c in captions if isinstance(c,dict) and re.fullmatch(r'c[1-8]',str(c.get('id','')))]
    if not 4<=len(cards)<=8 or {c['id'] for c in cards}!={f'c{i}' for i in range(1,len(cards)+1)}:return markup
    if not re.search(r'\b(?:match\w*|classif\w*|sort\w*|categor\w*|fact|opinion|sequence|order\w*)\b',
                     str(exercise.get('mechanic','')).replace('_',' ')+' '+str(exercise.get('directions','')),re.I):return markup
    from core.authored_wording import instruction_start
    for c in cards:
        text=c.get('text')
        if (not isinstance(text,str) or not 12<=len(text.strip())<=120 or not re.search(r'[a-z]\s+[a-z]',text,re.I)
                or instruction_start(text) or 'caption_'+c['id'] not in blocks):return markup
    parser=CanonicalTextContainers(blocks);parser.feed(markup);parser.close()
    if parser.stack:return markup
    used=set();assets=set();paths=[]
    def visit(children,path=(),parent=None,inside=False):
        """Find a normal-flow insertion point outside filled fields and narrow cells."""
        for index,node in enumerate(children):
            if isinstance(node,str) or 'comment' in node:continue
            attrs=dict(node['attrs']);slot=canonical_content_slot(attrs.get('data-content'),blocks)
            if slot:used.add(slot)
            if attrs.get('data-asset'):assets.add(attrs['data-asset'])
            ancestry=path+((children,index,parent),)
            if not inside and slot and slot.startswith('question_'):paths.append(ancestry)
            visit(node['children'],ancestry,node['tag'],inside or bool(slot))
    visit(parser.root)
    if any('caption_'+c['id'] in used or c['id'] in assets for c in cards) or not paths:return markup
    anchor=next(((children,index) for children,index,parent in reversed(paths[0]) if parent in {None,'div','section'}),None)
    if anchor is None:return markup
    font=config.get('minimum_text_pt',12)
    rows=[]
    for offset in range(0,len(cards),2):
        cells=[{'tag':'td','attrs':[('style','padding:2mm;vertical-align:top;border:0.3mm solid #A8C8CE')],
            'children':[{'tag':'p','attrs':[('data-content','caption_'+card['id']),
                ('style',f'font-size:{font}pt;line-height:1.2;margin:0')],'children':[]}]} for card in cards[offset:offset+2]]
        rows.append({'tag':'tr','attrs':[],'children':cells})
    table={'tag':'table','attrs':[('style','width:180mm;table-layout:fixed;border-collapse:collapse;margin:0 0 2mm')],'children':rows}
    children,index=anchor;children.insert(index,table)
    return ''.join(literal_html(node) for node in parser.root)
