"""Close omitted print-fragment end tags without guessing across nonoptional containers."""
import re
from html.parser import HTMLParser

VOID={'img','br'}
BLOCKS={'div','section','p','h1','h2','h3','h4','h5','h6','ul','ol','table'}
OPTIONAL={'p','li','td','th','tr','thead','tbody'}


def balance_print_fragment(markup: str) -> str:
    """Restore standard optional/trailing closes, preserving text and start attributes.

    Crossed nonoptional tags and orphan closing tags require an explicit model
    repair. Normal content, CSS, asset and geometry validators still run.
    """
    class Probe(HTMLParser):
        """Leave already balanced literal fragments unchanged by optional HTML rules."""
        def __init__(self):
            """Track whether ordinary nesting is already complete."""
            super().__init__();self.stack=[];self.valid=True

        def handle_starttag(self,tag,attrs):
            """Track nonvoid openings."""
            if tag not in VOID: self.stack.append(tag)

        def handle_endtag(self,tag):
            """Check lexical end-tag order without repairing it."""
            if tag in VOID: return
            if not self.stack or self.stack[-1]!=tag: self.valid=False
            else: self.stack.pop()

        def handle_startendtag(self,tag,attrs):
            """Self-closing containers create no open scope."""
            return

    probe=Probe();probe.feed(markup);probe.close()
    optional=not (probe.valid and not probe.stack)

    class Balancer(HTMLParser):
        """Keep literal content while tracking the open-element stack."""
        def __init__(self):
            """Disable entity decoding to retain text byte-for-byte."""
            super().__init__(convert_charrefs=False)
            self.parts=[];self.stack=[]

        def close_top(self):
            """Insert an omitted end tag without removing content or attributes."""
            self.parts.append('</'+self.stack.pop()+'>')

        def handle_starttag(self,tag,attrs):
            """Apply only standard optional paragraph/list/table end rules."""
            if optional:
                if self.stack and self.stack[-1]=='p' and tag in BLOCKS: self.close_top()
                if self.stack and tag=='li' and self.stack[-1]=='li': self.close_top()
                if self.stack and tag in {'td','th'} and self.stack[-1] in {'td','th'}: self.close_top()
                if tag=='tr':
                    if self.stack and self.stack[-1] in {'td','th'}: self.close_top()
                    if self.stack and self.stack[-1]=='tr': self.close_top()
                if tag in {'thead','tbody'}:
                    while self.stack and self.stack[-1] in {'td','th','tr'}: self.close_top()
                    if self.stack and self.stack[-1] in {'thead','tbody'}: self.close_top()
            self.parts.append(self.get_starttag_text())
            if tag not in VOID: self.stack.append(tag)

        def handle_startendtag(self,tag,attrs):
            """Retain self-closing elements without phantom stack entries."""
            self.parts.append(self.get_starttag_text())

        def handle_endtag(self,tag):
            """Ignore void ends and close only omitted optional ancestors before a real end."""
            if tag in VOID: return
            if tag not in self.stack:
                raise ValueError(f'Exercise layout tags must be balanced: orphan </{tag}>; open tags {self.stack}')
            while self.stack[-1]!=tag:
                if self.stack[-1] not in OPTIONAL:
                    raise ValueError(f'Exercise layout tags must be balanced: expected </{self.stack[-1]}> before </{tag}>; open tags {self.stack}')
                self.close_top()
            self.stack.pop();self.parts.append('</'+tag+'>')

        def handle_data(self,value):
            """Retain printed text, including comparison signs."""
            self.parts.append(value)

        def handle_entityref(self,name):
            """Preserve named entities."""
            self.parts.append('&'+name+';')

        def handle_charref(self,name):
            """Preserve numeric entities."""
            self.parts.append('&#'+name+';')

        def handle_comment(self,value):
            """Keep comments visible to the strict content guard."""
            self.parts.append('<!--'+value+'-->')

        def handle_decl(self,value):
            """Retain declarations for the normal fragment validator."""
            self.parts.append('<!'+value+'>')

    parser=Balancer();parser.feed(markup);parser.close()
    while parser.stack: parser.close_top()
    return ''.join(parser.parts)


def reject_truncated_tag(markup: str) -> None:
    """Reject a dangling tag token instead of accepting it as student prose."""
    if re.search(r'<\s*/?\s*[A-Za-z][^>]*$',markup):
        raise ValueError('Exercise layout tags must be balanced: incomplete tag at end of HTML; complete its syntax without deleting content')


def structural_signature(markup: str) -> list:
    """Compare all start tags, functional attributes and text while ignoring end tags."""
    class Signature(HTMLParser):
        """Keep ordered text and open elements for a closing-tag-only correction."""
        def __init__(self):
            """Decode equivalent HTML entities and track the token sequence."""
            super().__init__(convert_charrefs=True);self.parts=[]

        def handle_starttag(self,tag,attrs):
            """Keep duplicate attributes visible and preserve every value."""
            self.parts.append(('tag',tag,tuple(sorted(attrs,key=lambda a:a[0]))))

        def handle_startendtag(self,tag,attrs):
            """Treat a self-closing container as its equivalent open/close pair."""
            self.handle_starttag(tag,attrs)

        def handle_data(self,value):
            """Join data split only by closing tags, without reordering printed words."""
            if self.parts and self.parts[-1][0]=='text':
                self.parts[-1]=('text',self.parts[-1][1]+value)
            else: self.parts.append(('text',value))

        def handle_comment(self,value):
            """Preserve comments so syntax repair cannot hide unsupported content."""
            self.parts.append(('comment',value))

        def handle_decl(self,value):
            """Preserve declarations instead of silently dropping them."""
            self.parts.append(('decl',value))

    parser=Signature();parser.feed(markup);parser.close()
    return [('text',' '.join(p[1].split())) if p[0]=='text' else p
            for p in parser.parts if p[0]!='text' or p[1].strip()]


def merge_structural_repair(original: dict, correction: dict) -> dict:
    """Adopt only corrected end-tag structure; retain the complete exercise and its artwork."""
    from copy import deepcopy
    if not isinstance(correction,dict) or not isinstance(correction.get('html'),str):
        raise ValueError('Exercise layout tags must be balanced: structural repair needs HTML')
    if structural_signature(original['html'])!=structural_signature(correction['html']):
        raise ValueError('Exercise layout tags must be balanced: structural repair must preserve all start tags, attributes and printed wording')
    result=deepcopy(original);result['html']=correction['html'];result.pop('_syntax_only_repair',None)
    return result
