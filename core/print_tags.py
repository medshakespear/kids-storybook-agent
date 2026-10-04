"""Shared semantic wrapper aliases for safe static print fragments."""

TAG_ALIASES = {
    'i': 'em',
    'label': 'span',
    'header': 'div',
    'footer': 'div',
    'main': 'section',
    'article': 'section',
    'figure': 'div',
    'figcaption': 'p',
}

# These attributes do not print and cannot select styles in our inline-only input.
PASSIVE_ATTRIBUTES = {'class', 'id', 'role', 'title', 'alt', 'aria-label',
                      'aria-labelledby', 'aria-describedby'}


def normalize_print_markup(markup: str) -> str:
    """Map static wrappers and remove inert metadata without dropping printed content."""
    import html
    from html.parser import HTMLParser

    class Normalizer(HTMLParser):
        """Preserve structural errors and unsafe attributes for downstream validators."""
        def __init__(self):
            """Collect the equivalent static print fragment."""
            super().__init__(convert_charrefs=True)
            self.parts = []

        def start(self, tag, attrs, self_closing=False):
            """Serialize all functional attributes exactly; strip only passive metadata."""
            tag = TAG_ALIASES.get(tag, tag)
            retained = [(key,value) for key,value in attrs if key not in PASSIVE_ATTRIBUTES]
            rendered = ' '.join(key if value is None else f'{key}="{html.escape(value,quote=True)}"'
                                for key,value in retained)
            self.parts.append('<'+tag+(' '+rendered if rendered else '')+('/>' if self_closing else '>'))

        def handle_starttag(self, tag, attrs):
            """Normalize a static wrapper without changing its children."""
            self.start(tag,attrs)

        def handle_startendtag(self, tag, attrs):
            """Preserve self-closing syntax for the print validator."""
            self.start(tag,attrs,True)

        def handle_endtag(self, tag):
            """Map closing wrappers symmetrically and retain nesting errors."""
            self.parts.append('</'+TAG_ALIASES.get(tag,tag)+'>')

        def handle_data(self, data):
            """Retain every text character with correct escaping."""
            self.parts.append(html.escape(data,quote=False))

        def handle_comment(self, data):
            """Keep comments visible to existing content checks."""
            self.parts.append('<!--'+data+'-->')

        def handle_decl(self, data):
            """Retain declarations rather than silently accepting non-fragment HTML."""
            self.parts.append('<!'+data+'>')

    parser = Normalizer()
    parser.feed(markup)
    parser.close()
    return ''.join(parser.parts)
