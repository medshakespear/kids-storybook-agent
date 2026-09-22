"""Render AI-authored printable compositions inside a restricted HTML/CSS boundary."""
from __future__ import annotations

import base64
import html
import re
from html.parser import HTMLParser
from pathlib import Path

import tinycss2
from weasyprint import HTML, default_url_fetcher

TAGS = {'div', 'section', 'p', 'span', 'strong', 'b', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'br', 'img'}
PROPERTIES = {'color', 'background-color', 'border', 'border-color', 'border-width',
              'border-style', 'border-radius', 'border-top', 'border-bottom',
              'border-left', 'border-right', 'padding', 'padding-top', 'padding-bottom',
              'padding-left', 'padding-right', 'margin', 'margin-top', 'margin-bottom',
              'margin-left', 'margin-right', 'width', 'height', 'min-height', 'max-height',
              'max-width', 'font-size', 'font-weight', 'font-style', 'line-height',
              'text-align', 'vertical-align', 'display', 'flex-direction', 'flex-wrap',
              'align-items', 'justify-content', 'flex-basis', 'flex-grow', 'flex-shrink',
              'border-collapse', 'border-spacing', 'table-layout', 'letter-spacing',
              'background', 'font-family', 'box-sizing', 'text-transform',
              'text-decoration', 'object-fit', 'object-position', 'overflow-wrap',
              'word-wrap', 'min-width', 'align-self', 'flex', 'list-style-type',
              'list-style-position', 'border-top-left-radius', 'border-top-right-radius',
              'border-bottom-left-radius', 'border-bottom-right-radius',
              'gap', 'row-gap', 'column-gap'}


def clean_style(value: str) -> str:
    """Allow print layout declarations, excluding resource loading and hidden content."""
    if re.search(r'[\\@<>]|url\s*\(|expression\s*\(|var\s*\(', value, re.I):
        raise ValueError('Unsupported CSS resource or expression')
    declarations = tinycss2.parse_declaration_list(value, skip_comments=True, skip_whitespace=True)
    result = []
    for decl in declarations:
        if decl.type != 'declaration':
            raise ValueError('Malformed inline CSS: use property:value declarations separated by semicolons')
        if decl.lower_name not in PROPERTIES:
            raise ValueError(f'Unsupported CSS property "{decl.lower_name}"; remove it or use a listed print property')
        # Priority flags are unnecessary in these isolated fragments; keep the value.
        rendered = tinycss2.serialize(decl.value).strip()
        name = decl.lower_name
        if name == 'display' and rendered.lower() == 'none':
            raise ValueError('CSS display:none hides worksheet content; remove that declaration')
        negative = r'(?<![\w.])-\d*\.?\d+(?:[a-zA-Z]+|%)?'
        if name.startswith(('margin', 'padding')) or name == 'letter-spacing':
            # Negative spacing is cosmetic; normalize it before layout instead of
            # spending another API call. The resulting geometry is still checked.
            rendered = re.sub(negative, '0', rendered)
        elif name in {'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height',
                      'flex-basis', 'flex-grow', 'flex-shrink', 'border-spacing', 'border-width',
                      'gap', 'row-gap', 'column-gap'} or name.endswith('radius'):
            if re.search(negative, rendered):
                raise ValueError(f'CSS {name}:{rendered[:80]} has a negative size; use a nonnegative dimension')
        # Background angles may legitimately be negative. A border style of
        # "hidden" removes a border, not the content. Neither hides a worksheet.
        if decl.lower_name == 'font-size':
            match = re.fullmatch(r'(\d+(?:\.\d+)?)(pt|px)', rendered, re.I)
            if not match or float(match[1]) <= 0:
                raise ValueError('font-size must be a positive pt or px value, e.g. 14pt or 20px; avoid relative units')
            points = float(match[1]) * (0.75 if match[2].lower() == 'px' else 1)
            # Normalize typography before measuring layout; never scale the whole PDF.
            rendered = f'{max(11, min(40, points)):g}pt'
        if decl.lower_name == 'line-height':
            try:
                if float(rendered) < 1.15:
                    raise ValueError('Line height must be at least 1.15')
            except ValueError:
                raise ValueError('Use a numeric line-height of at least 1.15') from None
        result.append(f'{decl.lower_name}:{rendered}')
    return ';'.join(result)


class PrintFragment(HTMLParser):
    """Rebuild a printable fragment; only declared asset IDs can become images."""

    def __init__(self, assets: dict[str, str], preview: bool = False):
        """Track allowed images, nesting, and all image references."""
        super().__init__(convert_charrefs=True)
        self.assets, self.preview = assets, preview
        self.parts, self.stack, self.used = [], [], set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Validate tags and attributes and construct safe output markup."""
        if tag not in TAGS:
            raise ValueError(f'Unsupported HTML tag: {tag}')
        data = dict(attrs)
        if len(data) != len(attrs) or set(data) - {'style', 'data-asset', 'colspan', 'rowspan'}:
            raise ValueError('Only style, data-asset, colspan and rowspan attributes are allowed')
        attributes = []
        if 'style' in data:
            attributes.append('style="' + html.escape(clean_style(data['style']), quote=True) + '"')
        for key in ('colspan', 'rowspan'):
            if key in data:
                if tag not in {'td', 'th'} or not re.fullmatch('[1-6]', data[key]):
                    raise ValueError('Invalid table span')
                attributes.append(f'{key}="{data[key]}"')
        if tag == 'img':
            asset = data.get('data-asset')
            if asset not in self.assets:
                raise ValueError('Image must reference a declared data-asset ID')
            self.used.add(asset)
            if self.preview:
                source = 'data:image/svg+xml;base64,' + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024"><rect width="1024" height="1024" fill="#e5f2f4"/></svg>').decode()
            else:
                source = 'data:image/png;base64,' + base64.b64encode(Path(self.assets[asset]).read_bytes()).decode()
            attributes.append(f'src="{source}"')
            if not re.search(r'height\s*:\s*[1-9][\d.]*mm', data.get('style', '')):
                raise ValueError('Every image needs an explicit positive height in mm')
            if not re.search(r'(?<!-)\bwidth\s*:\s*[1-9][\d.]*(mm|%)', data.get('style', '')):
                raise ValueError('Every image needs an explicit positive width in mm or percent')
        elif 'data-asset' in data:
            raise ValueError('data-asset belongs only on img elements')
        self.parts.append(f'<{tag} ' + ' '.join(attributes) + '>')
        if tag not in {'br', 'img'}:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Accept self-closing image and break elements only."""
        if tag not in {'img', 'br'}:
            raise ValueError('Only img and br may be self-closing')
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        """Reject malformed nesting instead of silently rearranging a worksheet."""
        if not self.stack or self.stack.pop() != tag:
            raise ValueError('HTML tags must be balanced and correctly nested')
        self.parts.append(f'</{tag}>')

    def handle_data(self, data: str) -> None:
        """Escape model-written text while preserving ordinary printable symbols."""
        self.parts.append(html.escape(data))


def fragment(page: dict, preview: bool = False) -> str:
    """Sanitize one authored page and require all declared artwork to be used."""
    assets = {a['id']: a.get('path', '') for a in page['images']}
    parser = PrintFragment(assets, preview)
    parser.feed(page['html'])
    parser.close()
    if parser.stack or parser.used != set(assets):
        raise ValueError('Close every HTML tag and use every declared illustration')
    return ''.join(parser.parts)


def data_only_fetcher(url: str, *args, **kwargs):
    """Block network and filesystem fetches during PDF layout."""
    if not url.startswith(('data:image/png;base64,', 'data:image/svg+xml;base64,')):
        raise ValueError('Only internally embedded artwork is allowed')
    return default_url_fetcher(url, *args, **kwargs)


def document_markup(bodies: list[str], font: int = 13) -> str:
    """Provide page boundaries and readable defaults without choosing activity layouts."""
    css = f'''@page {{size:A4;margin:12mm;}}
    * {{box-sizing:border-box;}} body {{margin:0;font-family:DejaVu Sans,sans-serif;color:#233544;font-size:{font}pt;line-height:1.3;}}
    article {{width:186mm;min-height:268mm;break-after:page;}}
    article:last-child {{break-after:auto;}}
    img {{object-fit:contain;max-width:100%;}} h1,h2,h3,h4,h5,h6,p {{margin:0 0 3mm;}}
    h4,h5,h6 {{font-size:1em;}}
    table {{width:100%;table-layout:fixed;}} td,th {{vertical-align:top;}}
    .key {{column-count:2;column-gap:8mm;font-size:10pt;}}
    .key section {{break-inside:avoid;margin:0 0 5mm;border-top:1mm solid #188a91;padding-top:2mm;}}
    .key h3 {{font-size:11pt;}} .key p {{font-size:10pt;}}
    '''
    return '<html><head><style>' + css + '</style></head><body>' + ''.join('<article>' + b + '</article>' for b in bodies) + '</body></html>'


def check_document(document, expected: int) -> None:
    """Reject pagination and out-of-bounds content rather than shrinking or clipping."""
    if len(document.pages) != expected:
        raise ValueError(f'Design overflow: expected {expected} pages, got {len(document.pages)}; reduce content or spacing')
    right, bottom = 198 * 96 / 25.4, 283 * 96 / 25.4
    violations = []
    for page_number, page in enumerate(document.pages, 1):
        for box in page._page_box.descendants():
            if box.element_tag not in {None, 'html', 'body', 'article'}:
                dx = box.border_box_x() + box.border_width() - right
                dy = box.border_box_y() + box.border_height() - bottom
                if dx > 1 or dy > 1:
                    violations.append((max(dx, dy), f'page {page_number} <{box.element_tag}>: right overflow {max(0, dx)*25.4/96:.1f}mm, bottom overflow {max(0, dy)*25.4/96:.1f}mm'))
    if violations:
        details = '; '.join(dict.fromkeys(v for _, v in sorted(violations, reverse=True)))
        raise ValueError('Design content extends outside printable bounds: ' + details[:650]
                         + '. Reflow within 186mm width and 265mm height: reduce panel/image heights, padding and margins; use auto-width table cells. Preserve readable text and response space.')


def check_page(page: dict, font: int) -> None:
    """Preflight AI layout before spending image quota using identical image dimensions."""
    markup = document_markup([fragment(page, preview=True)], font)
    check_document(HTML(string=markup, url_fetcher=data_only_fetcher).render(), 1)


def pack_markup(pack: dict, config: dict, preview: bool = False) -> str:
    """Compose model-authored pages and the single answer sheet for either render pass."""
    bodies = [fragment(pack['cover'], preview)] + [fragment(p, preview) for p in pack['pages']]
    keys = ''.join(f'<section><h3>{i}. {html.escape(p["title"])}</h3><p>{html.escape(p["answers"])}</p></section>' for i, p in enumerate(pack['pages'], 1))
    bodies.append('<h1>Answer Key</h1><p>Activity numbers match the student pages. Creative answers may vary.</p><div class="key">' + keys + '</div>')
    return document_markup(bodies, config.get('student_font_pt', 13))


def preflight_pack(pack: dict, config: dict) -> None:
    """Check the assembled book including the answer sheet before image API spending."""
    doc = HTML(string=pack_markup(pack, config, preview=True), url_fetcher=data_only_fetcher).render()
    check_document(doc, len(pack['pages']) + 2)


def build_creative_pdf(pack: dict, config: dict, output_path: str | Path) -> Path:
    """Preserve AI-authored cover and student designs and append one compact answer key."""
    doc = HTML(string=pack_markup(pack, config), url_fetcher=data_only_fetcher).render()
    check_document(doc, len(pack['pages']) + 2)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.write_pdf(str(target))
    return target
