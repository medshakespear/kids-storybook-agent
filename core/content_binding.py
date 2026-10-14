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
TEXT_DECORATIONS = {'padding','padding-top','padding-right','padding-bottom','padding-left',
                    'margin','margin-top','margin-right','margin-bottom','margin-left',
                    'border','border-top','border-right','border-bottom','border-left',
                    'border-color','border-width','border-style','border-radius'}


def canonical_content_slot(slot: str | None, blocks: dict) -> str | None:
    """Resolve a bare declared caption ID without guessing unknown or task slots."""
    if isinstance(slot, str) and slot not in blocks and 'caption_' + slot in blocks:
        return 'caption_' + slot
    return slot


def diagram_label(value: str) -> bool:
    """Recognize a complete short diagram identifier, never directions or answers."""
    return bool(re.fullmatch(r'(?:node|point|station|zone|vertex|belt|claim|record)\s+'
                             r'(?:[a-z](?:[1-9]|[12][0-9]|30)?|[1-9]|[12][0-9]|30):?',
                             value.strip(),re.I))


def exercise_caption_limit(config: dict, render_mode: str) -> int:
    """Use the mixed profile for both page modes while retaining legacy exact limits."""
    limit = config.get('context_caption_limit',6) if render_mode == 'authored' or config.get('stimulus_limit') else 6
    if type(limit) is not int or not 1 <= limit <= 24:
        raise ValueError('Context caption limit must be between 1 and 24')
    return limit


def tip_heading(value: str) -> bool:
    """Recognize a short tip heading alone, never a tip's instruction or solution."""
    return len(value) <= 60 and bool(re.fullmatch(
        r'(?:challenge\s+tip|tip(?:\s+for\s+[a-z]+(?:[ -][a-z]+){0,2})?)\s*:',value.strip(),re.I))


def goal_heading(value: str) -> bool:
    """Recognize only a standalone goal label, never its following task or answer."""
    return bool(re.fullmatch(r'(?:activity\s+)?goal\s*:',value.strip(),re.I))


def evidence_heading(value: str) -> bool:
    """Recognize complete claim/record headings, never their content or instructions."""
    return bool(re.fullmatch(r'(?:visitor guide claims|visitor claims|measurement records|'
                             r'objective measurement records|objective measurements)\s*:?',value.strip(),re.I))


def caption_budget_available(captions: list, text: str, *, context_limit: int = 6, table_ids=None) -> bool:
    """Keep six contextual captions and up to eight short diagram identifiers."""
    if not isinstance(captions, list):
        return False
    captions = [c for c in captions if not isinstance(c,dict) or c.get('id') not in (table_ids or set())]
    labels = sum(isinstance(c, dict) and isinstance(c.get('text'), str)
                 and diagram_label(c['text']) for c in captions)
    return labels < 8 if diagram_label(text) else len(captions) - labels < context_limit


def validate_caption_budget(captions: list, *, table_ids: set[str] | None = None, context_limit: int = 6) -> None:
    """Reject excessive content while keeping diagram markers separate from prose."""
    if type(context_limit) is not int or not 1 <= context_limit <= 24:
        raise ValueError('Context caption limit must be between 1 and 24')
    error = ('Exercise captions need at most six contextual labels and eight diagram identifiers'
             if context_limit == 6 else f'Exercise captions need at most {context_limit} contextual labels and eight diagram identifiers')
    table_ids = table_ids or set()
    if len(table_ids) > 36:
        raise ValueError('Exercise tables need at most 36 short headers/data cells')
    if not isinstance(captions, list) or len(captions) > context_limit + 8 + len(table_ids):
        raise ValueError(error)
    captions = [c for c in captions if not isinstance(c,dict) or c.get('id') not in table_ids]
    labels = sum(isinstance(c, dict) and isinstance(c.get('text'), str)
                 and diagram_label(c['text']) for c in captions)
    if labels > 8 or len(captions) - labels > context_limit:
        raise ValueError(error)


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
        self.seen_metadata = set()
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
        tag = TAG_ALIASES.get(node.get('tag',''),node.get('tag',''))
        text_block = tag in {'p','div','section'}
        if 'comment' in node or (tag not in INLINE and not text_block):
            return None
        decorated = False
        for key,value in node['attrs']:
            if key!='style': return None
            declarations = (value or '').split(';')
            properties = {d.split(':',1)[0].strip().lower() for d in declarations if d.strip()}
            if properties - TEXT_STYLES - TEXT_DECORATIONS:
                return None
            decorated = bool(properties & TEXT_DECORATIONS)
        if tag=='br': return ' '
        pieces = [self.plain_text(child) for child in node['children']]
        if any(p is None for p in pieces):
            return None
        value = ''.join(pieces)
        # A colored/padded label may be harmless formatting around an exact
        # canonical copy. An empty bordered panel or underline is work space,
        # so it must never disappear during whole-container replacement.
        if decorated and (not value.strip() or re.fullmatch(r'[_\s]+',value)):
            return None
        if text_block:
            # Empty block containers can be independent working space. Keep
            # them out of text-only canonical replacement even without a size.
            return ' '+value+' ' if value.strip() else None
        return value

    def render(self, node, *, inside_slot: bool = False) -> str:
        """Add a named slot only when the entire text-only container matches one canonical block."""
        if isinstance(node,str): return html.escape(node,quote=False)
        if 'comment' in node: return '<!--'+node['comment']+'-->'
        tag,attrs = node['tag'],list(node['attrs'])
        block = canonical_content_slot(dict(attrs).get('data-content'), self.text_blocks)
        attrs = [(key, block if key == 'data-content' else value) for key, value in attrs]
        if not inside_slot and block is None and TAG_ALIASES.get(tag,tag) in CONTAINERS:
            node = self.separate_canonical_prefix(node)
        duplicate_caption = False
        if (not inside_slot and block is None and TAG_ALIASES.get(tag,tag) in CONTAINERS
                and {'name','date'}.issubset(self.text_blocks)):
            pieces = [self.plain_text(child) for child in node['children']]
            value = ' '.join(''.join(pieces).split()).casefold() if all(p is not None for p in pieces) else ''
            combined = re.fullmatch(r'(name|date)\s*:\s*[_\s]{3,}\s+(name|date)\s*:\s*[_\s]{3,}',value)
            if combined and combined[1] != combined[2]:
                # Only blank identification fields are metadata. Keep the outer
                # styling; bind both fields independently so normal deduplication
                # and canonical filling apply without swallowing student work.
                children = [{'tag':'span','attrs':[('data-content',combined[1])],'children':[]},' ',
                            {'tag':'span','attrs':[('data-content',combined[2]),('style','margin-left:4mm')],'children':[]}]
                node = dict(node,children=children)
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
                date_label = bool(re.fullmatch(r'date\s*:\s*[_\s]*',value))
                if not matches and date_label and 'date' in self.text_blocks: matches=['date']
                primary_title = (tag=='h1' and len(self.primary_headings)==1 and node is self.primary_headings[0]
                                 and not self.explicit_title and bool(value) and len(value)<=180)
                if not matches and primary_title: matches=['title']
                if len(matches)==1 and (primary_title or matches[0] in {'name','date'} or any(isinstance(c,dict) for c in node['children'])):
                    # Raw unformatted copies retain the established duplicate handling.
                    attrs.append(('data-content',matches[0]))
        metadata = dict(attrs).get('data-content')
        if not inside_slot and metadata in {'name','date'}:
            pieces = [self.plain_text(child) for child in node['children']]
            if all(p is not None for p in pieces):
                value = ' '.join(''.join(pieces).split()).casefold()
                harmless = not value or bool(re.fullmatch(metadata+r'\s*:\s*[_\s]*',value))
                if harmless:
                    if metadata in self.seen_metadata:
                        # Omit only a redundant blank identification field. Never
                        # remove a question, media asset or meaningful filled value.
                        return ''
                    self.seen_metadata.add(metadata)
        attributes = ' '.join(f'{k}="{html.escape(v or "",quote=True)}"' for k,v in attrs)
        start = f'<{tag} {attributes}>'
        if tag in {'img','br'}: return start
        if duplicate_caption:
            return start+f'</{tag}>'
        if any(k=='data-content' for k,_ in attrs) and not any(k=='data-content' for k,_ in node['attrs']):
            return start+f'</{tag}>'
        return start+''.join(self.render(child,inside_slot=inside_slot or any(k=='data-content' for k,_ in attrs))
                             for child in node['children'])+f'</{tag}>'

    def separate_canonical_prefix(self, node) -> dict:
        """Bind complete text runs before or after protected siblings without consuming them.

        The remainder stays in the original wrapper and goes through normal
        content, asset and geometry validation. Questions are excluded because
        canonical questions already own their response areas.
        """
        pieces=[self.plain_text(child) for child in node['children']]
        if all(piece is not None for piece in pieces):
            return node  # Retain the existing whole-container and duplicate handling.
        children=[];run=[];texts=[]

        def flush():
            """Replace only one complete unique non-question block in a contiguous run."""
            value=' '.join(''.join(texts).split()).casefold()
            matches=[key for key,text in self.text_blocks.items()
                     if value and value==text and not key.startswith('question_')]
            if not matches:
                matches=[key for key in ('name','date') if key in self.text_blocks
                         and re.fullmatch(key+r'\s*:\s*[_\s]*',value)]
            if len(matches)==1:
                children.append({'tag':'span','attrs':[('data-content',matches[0])],'children':[]})
            else:
                children.extend(run)
            run.clear();texts.clear()

        for child,piece in zip(node['children'],pieces):
            if piece is None:
                flush();children.append(child)
            else:
                run.append(child);texts.append(piece)
        flush()
        return dict(node,children=children)


def bind_formatted_canonical_text(layout: str, blocks: dict[str,str]) -> str:
    """Bind whole formatted copies locally; leave unrelated wording for strict validation."""
    parser = CanonicalTextContainers(blocks)
    parser.feed(layout)
    parser.close()
    if parser.stack: raise ValueError('Exercise layout tags must be balanced')
    return ''.join(parser.render(node) for node in parser.root)


def bind_standard_heading(layout: str, exercise: dict, *, context_limit: int = 6, table_ids=None) -> str:
    """Register allowlisted standalone labels without accepting independent task wording."""
    parser = CanonicalTextContainers({})
    parser.feed(layout)
    parser.close()
    if parser.stack:
        raise ValueError('Exercise layout tags must be balanced')
    candidates = []
    tool_labels = {'sort':'sorting', 'count':'counting', 'matching':'matching',
                   'maze':'maze', 'pattern':'pattern', 'balance':'size comparison',
                   'differences':'spot the differences'}
    activity_label = ('activity ' + tool_labels[exercise['mechanic']] + ' task'
                      if exercise.get('render_mode') == 'exact' and exercise.get('mechanic') in tool_labels else None)

    def visit(node, inside_slot=False):
        """Find whole text-only headings outside existing canonical content slots."""
        if isinstance(node,str) or 'comment' in node:
            return
        slotted = inside_slot or any(k=='data-content' for k,_ in node['attrs'])
        if not slotted and TAG_ALIASES.get(node['tag'],node['tag']) in CONTAINERS:
            pieces = [parser.plain_text(c) for c in node['children']]
            value = ' '.join(''.join(pieces).split()) if all(p is not None for p in pieces) else ''
            if (value.casefold() in {'zone id','zone id:'} or tip_heading(value) or goal_heading(value)
                    or evidence_heading(value) or diagram_label(value)
                    or value.casefold() == activity_label):
                candidates.append((node,value))
                return
        for child in node['children']:
            visit(child,slotted)

    for node in parser.root:
        visit(node)
    # Repeated labels and invalid/full caption manifests need normal validation.
    captions = exercise.get('captions',[])
    if not candidates or not isinstance(captions,list):
        return layout
    changed = False
    for node,text in candidates:
        if sum(value.casefold()==text.casefold() for _,value in candidates)!=1:
            continue
        if any(isinstance(c,dict) and str(c.get('text','')).strip().casefold()==text.casefold() for c in captions):
            continue
        if not caption_budget_available(captions,text, context_limit=context_limit, table_ids=table_ids):
            continue
        used = {c.get('id') for c in captions if isinstance(c,dict)}
        prefix = ('goal_label' if goal_heading(text) else
                  'tip_label' if tip_heading(text) else
                  'evidence_label' if evidence_heading(text) else
                  'diagram_label' if diagram_label(text) else 'zone_label')
        cid = next(f'{prefix}_{i}' for i in range(1,len(used)+2) if f'{prefix}_{i}' not in used)
        captions = list(captions)+[{'id':cid,'text':text}]
        exercise['captions'] = captions
        node['attrs'].append(('data-content','caption_'+cid))
        node['children'] = []
        changed = True
    if not changed:
        return layout
    return ''.join(parser.render(node) for node in parser.root)
