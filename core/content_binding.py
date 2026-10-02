"""Recover explicit content containers from complete, canonically identical formatted text."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from core.print_tags import TAG_ALIASES

CONTAINERS = {'h1','h2','h3','h4','h5','h6','p','div','section','span','td','th','li','strong','b','em'}
INLINE = {'span','strong','b','em','br'}
TEXT_STYLES = {'color','background-color','font-size','font-weight','font-style','font-family',
               'text-decoration','text-align','line-height','white-space'}


class CanonicalTextContainers(HTMLParser):
    """Inspect complete text-only containers without dropping graphics, work areas or extra tasks."""

    def __init__(self, blocks: dict[str,str]):
        """Capture canonical plain text and retain the original HTML structure."""
        super().__init__(convert_charrefs=True)
        self.root = []
        self.stack = []
        self.primary_headings = []
        self.explicit_title = False
        self.seen_captions = set()
        self.text_blocks = {}
        for key,value in blocks.items():
            parser = HTMLParser(convert_charrefs=True)
            chunks = []
            parser.handle_data = chunks.append
            parser.feed(value)
            self.text_blocks[key] = ' '.join(' '.join(chunks).split()).casefold()

    def append(self, item) -> None:
        """Append a retained node to its parent or the root."""
        (self.stack[-1]['children'] if self.stack else self.root).append(item)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Build a balanced tree without changing tag names or attribute values."""
        node = {'tag':tag,'attrs':attrs,'children':[]}
        self.append(node)
        if tag=='h1': self.primary_headings.append(node)
        if dict(attrs).get('data-content')=='title': self.explicit_title = True
        if tag not in {'img','br'}: self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        """Reject malformed nesting rather than silently repairing student content."""
        if not self.stack or self.stack[-1]['tag']!=tag:
            raise ValueError('Exercise layout tags must be balanced')
        self.stack.pop()

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Handle self-closing media and ordinary empty containers."""
        self.handle_starttag(tag,attrs)
        if tag not in {'img','br'}: self.handle_endtag(tag)

    def handle_data(self, value: str) -> None:
        """Retain all printed text for whole-container comparison."""
        self.append(value)

    def handle_comment(self, value: str) -> None:
        """Keep comments visible to the existing strict content compiler."""
        self.append({'comment':value})

    def plain_text(self, node) -> str | None:
        """Extract only inline formatting; reject media, slots, dimensions and nontext layout."""
        if isinstance(node,str): return node
        if 'comment' in node or TAG_ALIASES.get(node['tag'],node['tag']) not in INLINE:
            return None
        for key,value in node['attrs']:
            if key!='style': return None
            declarations = (value or '').split(';')
            if any(d.strip() and d.split(':',1)[0].strip().lower() not in TEXT_STYLES for d in declarations):
                return None
        if node['tag']=='br': return ' '
        pieces = [self.plain_text(child) for child in node['children']]
        return None if any(p is None for p in pieces) else ''.join(pieces)

    def render(self, node, *, inside_slot: bool = False) -> str:
        """Add a named slot only when the entire text-only container matches one canonical block."""
        if isinstance(node,str): return html.escape(node,quote=False)
        if 'comment' in node: return '<!--'+node['comment']+'-->'
        tag,attrs = node['tag'],list(node['attrs'])
        block = dict(attrs).get('data-content')
        duplicate_caption = False
        if not inside_slot and isinstance(block,str) and block.startswith('caption_') and block in self.text_blocks:
            if block in self.seen_captions:
                pieces = [self.plain_text(child) for child in node['children']]
                if all(p is not None for p in pieces):
                    value = ' '.join(''.join(pieces).split()).casefold()
                    if not value or value==self.text_blocks[block]:
                        attrs = [(k,v) for k,v in attrs if k!='data-content']
                        duplicate_caption = True
            else:
                self.seen_captions.add(block)
        if not inside_slot and TAG_ALIASES.get(tag,tag) in CONTAINERS and not any(k=='data-content' for k,_ in attrs):
            pieces = [self.plain_text(child) for child in node['children']]
            if all(p is not None for p in pieces):
                value = ' '.join(''.join(pieces).split()).casefold()
                matches = [key for key,text in self.text_blocks.items() if value==text]
                if not matches:
                    matches = [key for key,text in self.text_blocks.items() if key.startswith('question_')
                               and re.sub(r'^\d+[a-z]?\.\s*','',text)==value]
                if not matches and tag in {'h1','h2','h3','h4'}:
                    heading = re.sub(r'^(?:page|activity)\s+#?\d+\s*[:.\-–—]\s*','',value)
                    if heading==self.text_blocks.get('title'): matches=['title']
                if not matches and re.fullmatch(r'name\s*:\s*[_\s]*',value): matches=['name']
                primary_title = (tag=='h1' and len(self.primary_headings)==1 and node is self.primary_headings[0]
                                 and not self.explicit_title and bool(value) and len(value)<=180)
                if not matches and primary_title: matches=['title']
                if len(matches)==1 and (primary_title or any(isinstance(c,dict) for c in node['children'])):
                    # Raw unformatted copies retain the established duplicate handling.
                    attrs.append(('data-content',matches[0]))
        attributes = ' '.join(f'{k}="{html.escape(v or "",quote=True)}"' for k,v in attrs)
        start = f'<{tag} {attributes}>'
        if tag in {'img','br'}: return start
        if duplicate_caption:
            return start+f'</{tag}>'
        if any(k=='data-content' for k,_ in attrs) and not any(k=='data-content' for k,_ in node['attrs']):
            return start+f'</{tag}>'
        return start+''.join(self.render(child,inside_slot=inside_slot or any(k=='data-content' for k,_ in attrs))
                             for child in node['children'])+f'</{tag}>'


def bind_formatted_canonical_text(layout: str, blocks: dict[str,str]) -> str:
    """Bind whole formatted copies locally; leave unrelated wording for strict validation."""
    parser = CanonicalTextContainers(blocks)
    parser.feed(layout)
    parser.close()
    if parser.stack: raise ValueError('Exercise layout tags must be balanced')
    return ''.join(parser.render(node) for node in parser.root)


def bind_standard_heading(layout: str, exercise: dict) -> str:
    """Register a standalone tip heading without accepting any independent task wording."""
    parser = CanonicalTextContainers({})
    parser.feed(layout)
    parser.close()
    if parser.stack:
        raise ValueError('Exercise layout tags must be balanced')
    candidates = []

    def visit(node, inside_slot=False):
        """Find whole text-only headings outside existing canonical content slots."""
        if isinstance(node,str) or 'comment' in node:
            return
        slotted = inside_slot or any(k=='data-content' for k,_ in node['attrs'])
        if not slotted and TAG_ALIASES.get(node['tag'],node['tag']) in CONTAINERS:
            pieces = [parser.plain_text(c) for c in node['children']]
            if all(p is not None for p in pieces) and ' '.join(''.join(pieces).split()).casefold()=='challenge tip:':
                candidates.append(node)
                return
        for child in node['children']:
            visit(child,slotted)

    for node in parser.root:
        visit(node)
    # Repeated labels and invalid/full caption manifests need normal validation.
    captions = exercise.get('captions',[])
    if len(candidates)!=1 or not isinstance(captions,list) or len(captions)>=6:
        return layout
    if any(isinstance(c,dict) and str(c.get('text','')).strip().casefold()=='challenge tip:' for c in captions):
        return layout
    used = {c.get('id') for c in captions if isinstance(c,dict)}
    cid = next((f'tip_label_{i}' for i in range(1,8) if f'tip_label_{i}' not in used),None)
    captions = list(captions)+[{'id':cid,'text':'Challenge Tip:'}]
    exercise['captions'] = captions
    candidates[0]['attrs'].append(('data-content','caption_'+cid))
    candidates[0]['children'] = []
    return ''.join(parser.render(node) for node in parser.root)
