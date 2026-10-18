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
TEXT_DIMENSIONS={'width','height','min-width','max-width','min-height','max-height','display'}


def combined_metadata_fields(value: str) -> tuple[str, str] | None:
    """Recognize only two complete blank Name/Date fields, including Unicode spaces."""
    normalized = ' '.join(value.split()).casefold()
    match = re.fullmatch(r'(name|date)\s*:\s*[_\s]*(name|date)\s*:\s*[_\s]*', normalized)
    return (match[1], match[2]) if match and match[1] != match[2] else None


def metadata_nodes(fields: tuple[str, str]) -> list:
    """Create independent canonical fields without consuming nearby writing panels."""
    return [{'tag':'span','attrs':[('data-content',fields[0])],'children':[]}, ' ',
            {'tag':'span','attrs':[('data-content',fields[1]),('style','margin-left:4mm')],'children':[]}]


def canonical_content_slot(slot: str | None, blocks: dict) -> str | None:
    """Resolve declared namespace/body-suffix aliases; never guess source identity."""
    if not isinstance(slot,str) or slot in blocks:return slot
    matches={key for key in ('caption_'+slot,'stimulus_'+slot) if key in blocks}
    bare=slot
    while bare.startswith('stimulus_'):bare=bare[len('stimulus_'):]
    if bare.startswith('caption_'):bare=bare[len('caption_'):]
    if bare!=slot:
        matches.update(key for key in ('caption_'+bare,'stimulus_'+bare) if key in blocks)
    # Full declared IDs have precedence over optional body suffixes. Collisions
    # remain explicit errors rather than choosing a caption over a reading.
    if matches:return next(iter(matches)) if len(matches)==1 else slot
    for suffix in ('_text','_body','_content'):
        if bare.endswith(suffix):
            candidate='stimulus_'+bare[:-len(suffix)]
            if candidate in blocks:return candidate
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


def instruction_heading(value: str) -> bool:
    """Recognize a standalone rules label, never instructions following its colon."""
    return bool(re.fullmatch(r'(?:Design Rules for (?:Mirroring|Symmetry)|'
                             r'(?:Mirroring|Symmetry) (?:Design )?Rules)\s*:',value.strip(),re.I))


def evidence_heading(value: str) -> bool:
    """Recognize complete claim/record headings, never their content or instructions."""
    return bool(re.fullmatch(r'(?:visitor guide claims|visitor claims|measurement records|'
                             r'objective measurement records|objective measurements)\s*:?',value.strip(),re.I))


def source_heading(value: str) -> bool:
    """Recognize complete source-panel labels, never excerpts, directions or answers."""
    return bool(re.fullmatch(r'(?:museum placard|exhibit placard|museum label|exhibit label|'
                             r'student notes|field notes|source card|evidence card|source excerpt)\s*:?',
                             value.strip(),re.I))


def problem_heading(value: str) -> bool:
    """Recognize only a numbered problem label, never its task or solution."""
    return bool(re.fullmatch(r'(?:problem|question)\s+[1-9]\d?[a-z]?\s*[:.]?',value.strip(),re.I))


def definition_label(value: str) -> bool:
    """Recognize a short complete literacy definition, never tasks or numerical keys."""
    value=value.strip()
    if len(value)>120 or re.search(r'\d|[!?]|[.]\s*\S',value): return False
    if not re.match(r'^(?:can\s+be|(?:a|an|the)\s+(?:fact|opinion|statement|claim)\s+'
                    r'(?:is|can|means|tells|expresses))\b',value,re.I): return False
    from core.context_recovery import contextual_text
    return contextual_text(value)


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

    def __init__(self, blocks: dict[str,str], *, separate_protected: bool = False):
        """Capture canonical plain text and retain the original HTML structure."""
        super().__init__(convert_charrefs=True)
        self.separate_protected = separate_protected
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

    def plain_text(self, node, *, allow_text_dimensions: bool = False) -> str | None:
        """Read text formatting; optionally inspect sized text, never media, slots or workspace."""
        if isinstance(node,str): return node
        tag = TAG_ALIASES.get(node.get('tag',''),node.get('tag',''))
        text_block = tag in {'p','div','section'}
        if 'comment' in node or (tag not in INLINE and not text_block):
            return None
        decorated = False
        dimensioned = False
        for key,value in node['attrs']:
            if key!='style': return None
            declarations = (value or '').split(';')
            properties = {d.split(':',1)[0].strip().lower() for d in declarations if d.strip()}
            if properties - TEXT_STYLES - TEXT_DECORATIONS - (TEXT_DIMENSIONS if allow_text_dimensions else set()):
                return None
            if 'display' in properties and not re.search(r'(?:^|;)\s*display\s*:\s*(?:inline|inline-block|block)\s*(?:;|$)',value or '',re.I):
                return None
            decorated = bool(properties & TEXT_DECORATIONS)
            dimensioned = bool(properties & TEXT_DIMENSIONS)
        if tag=='br': return ' '
        pieces = [self.plain_text(child,allow_text_dimensions=allow_text_dimensions) for child in node['children']]
        if any(p is None for p in pieces):
            return None
        value = ''.join(pieces)
        # A colored/padded label may be harmless formatting around an exact
        # canonical copy. An empty bordered panel or underline is work space,
        # so it must never disappear during whole-container replacement.
        if (decorated or dimensioned) and (not value.strip() or re.fullmatch(r'[_\s|]+|(?:\[[_\s]*\]\s*)+',value)):
            return None
        if text_block:
            # Empty block containers can be independent working space. Keep
            # them out of text-only canonical replacement even without a size.
            return ' '+value+' ' if value.strip() else None
        return value

    def render(self, node, *, inside_slot: bool = False) -> str:
        """Add a named slot only when the entire text-only container matches one canonical block."""
        if isinstance(node,str):
            fields = combined_metadata_fields(node) if not inside_slot else None
            if fields and {'name','date'}.issubset(self.text_blocks):
                return ''.join(self.render(child) for child in metadata_nodes(fields))
            return html.escape(node,quote=False)
        if 'comment' in node: return '<!--'+node['comment']+'-->'
        tag,attrs = node['tag'],list(node['attrs'])
        block = canonical_content_slot(dict(attrs).get('data-content'), self.text_blocks)
        attrs = [(key, block if key == 'data-content' else value) for key, value in attrs]
        if not inside_slot and block is None and TAG_ALIASES.get(tag,tag) in CONTAINERS:
            node = self.separate_canonical_prefix(node)
        if (self.separate_protected and not inside_slot and block in self.text_blocks and not block.startswith('question_')
                and any(self.plain_text(child) is None for child in node['children'])):
            # Keep media, nested slots and independent work panels outside text
            # bindings. Only replace own wording if it is empty or an exact copy.
            pieces = [self.plain_text(child) for child in node['children']]
            own = ' '.join(''.join(p for p in pieces if p is not None).split()).casefold()
            # A complete canonical run may sit beside other retained text and
            # protected nodes. Isolate that whole run rather than consuming the
            # sibling captions, artwork or writing panels inside a filled slot.
            exact_runs=[i for i,piece in enumerate(pieces) if piece is not None
                        and ' '.join(piece.split()).casefold()==self.text_blocks[block]]
            if own and own!=self.text_blocks[block] and len(exact_runs)==1:
                index=exact_runs[0];children=list(node['children']);child=children[index]
                if isinstance(child,str):
                    children[index]={'tag':'span','attrs':[('data-content',block)],'children':[]}
                else:
                    children[index]=dict(child,attrs=list(child['attrs'])+[('data-content',block)],children=[])
                attrs=[(k,v) for k,v in attrs if k!='data-content']
                node=dict(node,attrs=attrs,children=children);block=None
            elif not own or own == self.text_blocks[block]:
                attrs = [(k,v) for k,v in attrs if k != 'data-content']
                children = []; inserted = False
                for child, piece in zip(node['children'], pieces):
                    if piece is None:
                        children.append(child)
                    elif not inserted:
                        children.append({'tag':'span','attrs':[('data-content',block)],'children':[]})
                        inserted = True
                if not inserted:
                    children.insert(0, {'tag':'span','attrs':[('data-content',block)],'children':[]})
                node = dict(node, attrs=attrs, children=children)
                block = None
        duplicate_caption = False
        if (not inside_slot and block is None and TAG_ALIASES.get(tag,tag) in CONTAINERS
                and {'name','date'}.issubset(self.text_blocks)):
            pieces = [self.plain_text(child) for child in node['children']]
            value = ' '.join(''.join(pieces).split()).casefold() if all(p is not None for p in pieces) else ''
            combined = combined_metadata_fields(value)
            if combined:
                # Only blank identification fields are metadata. Keep the outer
                # styling; bind both fields independently so normal deduplication
                # and canonical filling apply without swallowing student work.
                children = metadata_nodes(combined)
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
                fields = combined_metadata_fields(value)
                if fields and {'name','date'}.issubset(self.text_blocks):
                    children.extend(metadata_nodes(fields))
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


def bind_formatted_canonical_text(layout: str, blocks: dict[str,str], *, separate_protected: bool = False) -> str:
    """Bind whole formatted copies locally; leave unrelated wording for strict validation."""
    parser = CanonicalTextContainers(blocks, separate_protected=separate_protected)
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
    matching=bool(re.search(r'\b(?:match\w*|pair\w*|link\w*)\b',
        str(exercise.get('mechanic','')).replace('_',' ')+' '+str(exercise.get('directions','')),re.I))

    def matching_label(value):
        """Recognize a standalone A-H item marker only in a written matching activity."""
        return matching and bool(re.fullmatch(r'[A-H][.)]',value.strip()))

    def wrap_markers(children,inside=False):
        """Bind bare marker text without swallowing adjacent source or response nodes."""
        for index,node in enumerate(children):
            if isinstance(node,str):
                if not inside and matching_label(node):
                    children[index]={'tag':'span','attrs':[],'children':[node]}
            elif 'comment' not in node:
                wrap_markers(node['children'],inside or any(k=='data-content' for k,_ in node['attrs']))

    wrap_markers(parser.root)

    def visit(node, inside_slot=False):
        """Find whole text-only headings outside existing canonical content slots."""
        if isinstance(node,str) or 'comment' in node:
            return
        slotted = inside_slot or any(k=='data-content' for k,_ in node['attrs'])
        if not slotted and TAG_ALIASES.get(node['tag'],node['tag']) in CONTAINERS:
            pieces = [parser.plain_text(c,allow_text_dimensions=True) for c in node['children']]
            value = ' '.join(''.join(pieces).split()) if all(p is not None for p in pieces) else ''
            if (value.casefold().rstrip(':') in {'zone id','terms','numbered terms','definitions','descriptions'} or tip_heading(value) or goal_heading(value)
                    or evidence_heading(value) or source_heading(value) or definition_label(value) or diagram_label(value)
                    or instruction_heading(value) or problem_heading(value) or matching_label(value)
                    or (node['tag'] in {'h2','h3','h4','h5','h6'} and len(value)<=80
                        and re.fullmatch(r'[A-Za-z][A-Za-z :’\x27-]{0,65}\b(?:Design Challenge|Design Studio|Design Workshop)',value))
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
        existing=[c for c in captions if isinstance(c,dict) and str(c.get('text','')).strip().casefold()==text.casefold()]
        if len(existing)==1 and isinstance(existing[0].get('id'),str):
            node['attrs'].append(('data-content','caption_'+existing[0]['id']))
            node['children']=[]
            changed=True
            continue
        if existing:
            continue
        if not caption_budget_available(captions,text, context_limit=context_limit, table_ids=table_ids):
            continue
        used = {c.get('id') for c in captions if isinstance(c,dict)}
        prefix = ('goal_label' if goal_heading(text) else
                  'rules_label' if instruction_heading(text) else
                  'tip_label' if tip_heading(text) else
                  'source_label' if source_heading(text) else
                  'definition_label' if definition_label(text) else
                  'evidence_label' if evidence_heading(text) else
                  'diagram_label' if diagram_label(text) else
                  'problem_label' if problem_heading(text) else
                  'matching_label' if matching_label(text) else
                  'section_label' if text.casefold().rstrip(':') in {'terms','numbered terms','definitions','descriptions'} else
                  'design_heading' if re.search(r'Design (?:Challenge|Studio|Workshop)$',text) else 'zone_label')
        cid = next(f'{prefix}_{i}' for i in range(1,len(used)+2) if f'{prefix}_{i}' not in used)
        captions = list(captions)+[{'id':cid,'text':text}]
        exercise['captions'] = captions
        node['attrs'].append(('data-content','caption_'+cid))
        node['children'] = []
        changed = True
    if not changed:
        return layout
    return ''.join(parser.render(node) for node in parser.root)
