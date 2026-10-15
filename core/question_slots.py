"""Align stale layout labels with declared questions without inventing student tasks."""
import re

from core.content_binding import CanonicalTextContainers
from core.print_grid import literal_html


def normalize_question_slots(markup: str, blocks: dict, *, deduplicate_empty: bool = False) -> str:
    """Rebind an unambiguous typo; optionally detach repeated empty canonical placeholders.

    Meaningful unmatched wording, ambiguous mappings, graphics and nested content
    stay untouched for strict validation. Explicit blank writing panels are never
    consumed by an inferred question binding.
    """
    declared={key for key in blocks if key.startswith('question_')}
    parser=CanonicalTextContainers(blocks);parser.feed(markup);parser.close()
    if parser.stack: return markup
    nodes=[];literal_used=set()

    def visit(node):
        """Collect actual question slot attributes without reading labels inside prose."""
        if isinstance(node,str) or 'comment' in node: return
        slot=dict(node['attrs']).get('data-content')
        if isinstance(slot,str) and slot.startswith('question_'): nodes.append((node,slot))
        if slot: return  # Never infer ownership from wording inside another bound field.
        pieces=[parser.plain_text(c,allow_text_dimensions=True) for c in node['children']]
        value=' '.join(''.join(pieces).split()).casefold() if all(p is not None for p in pieces) else ''
        matches=[key for key,text in parser.text_blocks.items() if value and
                 (value==text or (key.startswith('question_') and re.sub(r'^[1-9]\d?[a-z]?[.]\s+','',text)==value))]
        if len(matches)==1 and matches[0] in declared: literal_used.add(matches[0])
        for child in node['children']: visit(child)

    for node in parser.root: visit(node)
    used={slot for _,slot in nodes if slot in declared}|literal_used
    missing=declared-used
    unknown=[(node,slot) for node,slot in nodes if slot not in declared]
    changed=False

    def task_text(value):
        """Ignore only a leading printed question label and harmless whitespace/case."""
        value=' '.join(value.split()).casefold()
        return re.sub(r'^[1-9]\d?[a-z]?[.)]\s+', '',value)

    def blank(node):
        """Recognize work surfaces, never an unverified task, picture or nested slot."""
        if isinstance(node,str):
            return not node.strip() or bool(re.fullmatch(r'[_\s|]+|(?:\[[_\s]*\]\s*)+',node.strip()))
        if ('comment' in node or node['tag'] in {'img','table'}
                or any(k.startswith('data-') for k,_ in node['attrs'])):
            return False
        return all(blank(child) for child in node['children'])

    for node,slot in unknown:
        pieces=[parser.plain_text(child,allow_text_dimensions=True) for child in node['children']]
        text=''.join(pieces) if all(piece is not None for piece in pieces) else None
        targets=[key for key in missing if text and task_text(text)==task_text(parser.text_blocks[key])]
        # A lone empty, unsized placeholder can only denote the lone missing
        # canonical question. Do not infer from position when there are several.
        sized=re.search(r'(?:^|;)\s*(?:height|min-height|max-height)\s*:',dict(node['attrs']).get('style','') or '',re.I)
        empty=all(isinstance(child,str) and not child.strip() for child in node['children'])
        if not targets and len(unknown)==1 and len(missing)==1 and empty and not sized:
            targets=list(missing)
        if len(targets)==1:
            key=targets[0]
            node['attrs']=[(k,key if k=='data-content' else v) for k,v in node['attrs']]
            missing.remove(key);changed=True
    if deduplicate_empty:
        for slot in declared:
            copies=[node for node,key in nodes if key==slot]
            if len(copies)<2: continue
            # Only redundant empty placeholders qualify. A prefilled duplicate
            # could be a different student action and must remain a strict error.
            occupied=[node for node in copies if any(not isinstance(c,str) or c.strip() for c in node['children'])]
            if occupied: continue
            keeper=copies[0]
            for node in copies:
                if node is keeper or any(not isinstance(c,str) or c.strip() for c in node['children']): continue
                node['attrs']=[(k,v) for k,v in node['attrs'] if k!='data-content']
                changed=True
    if not missing:
        for node,slot in unknown:
            if dict(node['attrs']).get('data-content')!=slot or not all(blank(child) for child in node['children']):
                continue
            # It has no task or answer in the shared spec. Keep its complete
            # frame and children as additional workspace, without a phantom ID.
            node['attrs']=[(k,v) for k,v in node['attrs'] if k!='data-content']
            changed=True
    return ''.join(literal_html(node) for node in parser.root) if changed else markup
