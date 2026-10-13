"""Restore omitted factual caption slots before lossless computed-page recovery."""
from copy import deepcopy
import html
import re
from core.content_binding import CanonicalTextContainers, canonical_content_slot, diagram_label
from core.context_recovery import contextual_text


def recover_missing_exact_context(page: dict) -> dict:
    """Add only declared factual context; never infer diagram-label positions or tasks.

    This is an internal recovery candidate, not an accepted page. The complete
    exercise compiler and actual print geometry must still validate the result.
    """
    result = deepcopy(page)
    exercise = result.get('exercise')
    if not isinstance(exercise,dict) or exercise.get('render_mode') != 'exact':
        return result
    captions = exercise.get('captions',[])
    if not isinstance(captions,list):
        return result
    known = {'caption_'+c['id']:c['text'] for c in captions
             if isinstance(c,dict) and isinstance(c.get('id'),str) and isinstance(c.get('text'),str)}
    parser = CanonicalTextContainers({})
    parser.feed(result['html']); parser.close()
    if parser.stack:
        return result
    slots, literals = set(), set()

    def visit(node):
        """Read complete existing containers so a literal copy is not printed twice."""
        if isinstance(node,str) or 'comment' in node:
            return
        slot = canonical_content_slot(dict(node['attrs']).get('data-content'),known)
        if slot:
            slots.add(slot)
        pieces = [parser.plain_text(c) for c in node['children']]
        if all(p is not None for p in pieces):
            literals.add(' '.join(''.join(pieces).split()).casefold())
        for child in node['children']:
            visit(child)

    for node in parser.root:
        visit(node)
    additions=[]
    for slot,text in known.items():
        if (slot in slots or ' '.join(text.split()).casefold() in literals
                or not re.fullmatch(r'caption_[a-z][a-z0-9_]{0,23}',slot)
                or not text.strip() or len(text.strip())>120
                or diagram_label(text) or not contextual_text(text)):
            continue
        # A missing identifier such as Node A needs a real attachment to its
        # diagram. Factual context can be printed as a standalone paragraph.
        additions.append(f'<p data-content="{html.escape(slot,quote=True)}"></p>')
    result['html'] += ''.join(additions)
    return result
