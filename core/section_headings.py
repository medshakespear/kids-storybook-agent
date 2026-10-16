"""Bind authored section headings from printed text or an adjacent retained source."""
from collections import Counter
import re

from core.content_binding import CanonicalTextContainers, caption_budget_available
from core.print_grid import literal_html


def bind_section_headings(markup: str, exercise: dict, config: dict, *, table_ids=None) -> str:
    """Recover missing caption declarations without inventing subject matter.

    Only explicit caption slots in heading elements qualify. A complete short
    printed heading is retained verbatim; an empty numbered section-title slot
    immediately before one declared source uses its label (or the word Source).
    IDs, answers and image prompts never supply new wording. Conflicting,
    repeated, nested, instructional and unanchored slots remain strict errors.
    """
    if not config.get('student_workbook') or exercise.get('render_mode')!='authored':return markup
    captions=exercise.get('captions',[])
    if not isinstance(captions,list):return markup
    parser=CanonicalTextContainers({});parser.feed(markup);parser.close()
    if parser.stack:return markup
    counts=Counter();known={s for c in captions if isinstance(c,dict) and isinstance(c.get('id'),str)
                          for s in (c['id'],'caption_'+c['id'])}
    stimuli=exercise.get('stimuli',[])
    sources={'stimulus_'+s['id']:s for s in (stimuli if isinstance(stimuli,list) else []) if isinstance(s,dict)
             and isinstance(s.get('id'),str) and isinstance(s.get('text'),str) and s['text'].strip()}

    def count(node):
        """Keep repeated unknown slots visible to the duplicate-content validator."""
        if isinstance(node,str) or 'comment' in node:return
        slot=dict(node['attrs']).get('data-content')
        if slot:counts[slot]+=1
        for child in node['children']:count(child)

    def source_anchor(node):
        """Accept only a single source slot through otherwise empty flow wrappers."""
        if isinstance(node,str) or 'comment' in node:return None
        slot=dict(node['attrs']).get('data-content')
        if slot:return sources.get(slot)
        if node['tag'] not in {'div','section','p','span'}:return None
        peers=[c for c in node['children'] if not isinstance(c,str) or c.strip()]
        return source_anchor(peers[0]) if len(peers)==1 else None

    def heading_slot(node):
        """Find a whole heading or its sole formatting child, never a mixed container."""
        slot=dict(node['attrs']).get('data-content','') or ''
        explicit_section=(node['tag'] in {'p','div','span'} and
                          re.fullmatch(r'caption_(?:sec|section)_(?:title|heading)_[1-9][0-9]?',slot))
        if node['tag'] not in {'h2','h3','h4','h5','h6'} and not explicit_section:return None
        target=node
        while not dict(target['attrs']).get('data-content'):
            peers=[c for c in target['children'] if not isinstance(c,str) or c.strip()]
            if len(peers)!=1 or not isinstance(peers[0],dict) or peers[0].get('tag') not in {'span','strong','b','em'}:return None
            target=peers[0]
        return target

    changed=False
    def visit(children,inside=False):
        """Use immediate sibling relationships rather than numbering inferred from IDs."""
        nonlocal changed
        peers=[c for c in children if not isinstance(c,str) or c.strip()]
        for index,node in enumerate(peers):
            if isinstance(node,str) or 'comment' in node:continue
            target=heading_slot(node) if not inside else None
            if target is not None:
                slot=dict(target['attrs']).get('data-content');cid=slot.removeprefix('caption_')
                pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in target['children']]
                if (slot.startswith('caption_') and slot not in known and counts[slot]==1
                        and re.fullmatch(r'[a-z][a-z0-9_]{0,23}',cid) and all(p is not None for p in pieces)):
                    text=' '.join(''.join(pieces).split())
                    if (not text and re.fullmatch(r'(?:sec|section)_(?:title|heading)_[1-9][0-9]?',cid)
                            and index+1<len(peers)):
                        source=source_anchor(peers[index+1])
                        if source is not None:text=source.get('label') or 'Source'
                    command=re.search(r'^(?:please\s+)?(?:(?:read|write|draw|count|sort|match|find|explain|calculate|solve|choose|complete|compare|create|use|help|answer|describe|trace|circle|connect|label|list|identify|record|respond|plan|draft|revise|rewrite|transform|color|colour|mark|select|check|cut|fold|measure|follow)\b|design\s+(?:a|an|the|your|each)\b)',str(text),re.I)
                    if (isinstance(text,str) and text.strip() and len(text)<=80 and not command
                            and not re.search(r'[!?\x00-\x1f]|\b(?:answer key|solution|correct answer)\b',text,re.I)
                            and caption_budget_available(captions,text,context_limit=config.get('context_caption_limit',6),table_ids=table_ids)):
                        captions.append({'id':cid,'text':text.strip()});known.add(slot)
                        target['children']=[];changed=True
            visit(node['children'],inside or bool(dict(node['attrs']).get('data-content')))

    for node in parser.root:count(node)
    visit(parser.root)
    if not changed:return markup
    exercise['captions']=captions
    return ''.join(literal_html(n) for n in parser.root)
