"""Render AI-authored printable compositions inside a restricted HTML/CSS boundary."""
from __future__ import annotations

import base64
import html
import re
from html.parser import HTMLParser
from pathlib import Path
from threading import RLock
from functools import lru_cache

import tinycss2
from weasyprint import HTML, default_url_fetcher
from core.paths import BASE_DIR
from core.task_visuals import page_visuals, answer_text

RENDER_LOCK = RLock()


@lru_cache(maxsize=1)
def brand_header() -> str:
    """Embed the original store logo; CSS removes only its surrounding white margin."""
    data = base64.b64encode((BASE_DIR / 'assets' / 'store-logo.png').read_bytes()).decode()
    return ('<div class="store-logo"><img alt="The Classroom Activity Collection" '
            f'src="data:image/png;base64,{data}"/></div>')


def cover_fragment(page: dict, preview: bool = False) -> str:
    """Reserve cover space for branding before the model-authored composition."""
    return brand_header() + fragment(page, preview)

TAGS = {'div', 'section', 'p', 'span', 'strong', 'b', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'br', 'img'}
TAG_ALIASES = {'i': 'em'}
INLINE_TAGS = {'span', 'strong', 'b', 'em'}
DROP_PROPERTIES = {'background-image', 'position', 'top', 'right', 'bottom', 'left', 'z-index'}
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
              'gap', 'row-gap', 'column-gap', 'white-space'}


def clean_style(value: str) -> str:
    """Allow print layout declarations, excluding resource loading and hidden content."""
    if re.search(r'[\\@<>]|url\s*\(|expression\s*\(|var\s*\(', value, re.I):
        raise ValueError('Unsupported CSS resource or expression')
    declarations = tinycss2.parse_declaration_list(value, skip_comments=True, skip_whitespace=True)
    result = []
    for decl in declarations:
        if decl.type != 'declaration':
            raise ValueError('Malformed inline CSS: use property:value declarations separated by semicolons')
        if decl.lower_name in DROP_PROPERTIES:
            continue
        if decl.lower_name not in PROPERTIES:
            raise ValueError(f'Unsupported CSS property "{decl.lower_name}"; remove it or use a listed print property')
        # Priority flags are unnecessary in these isolated fragments; keep the value.
        rendered = tinycss2.serialize(decl.value).strip()
        name = decl.lower_name
        if name == 'white-space':
            choices = {'normal': 'normal', 'nowrap': 'normal', 'pre': 'pre-wrap',
                       'pre-wrap': 'pre-wrap', 'pre-line': 'pre-line', 'break-spaces': 'pre-wrap'}
            if rendered.lower() not in choices:
                raise ValueError('Use white-space:normal, pre-wrap or pre-line')
            rendered = choices[rendered.lower()]
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
            # Line-height is cosmetic and safe to normalize locally. Do not spend
            # another model call because Gemini returned 1.0, "normal", or 110%.
            value = rendered.strip().lower()
            if value == 'normal':
                rendered = '1.3'
            elif re.fullmatch(r'\d+(?:\.\d+)?%', value):
                rendered = f'{max(1.15, float(value[:-1]) / 100):g}'
            else:
                try:
                    rendered = f'{max(1.15, float(value)):g}'
                except ValueError:
                    rendered = '1.3'
        result.append(f'{decl.lower_name}:{rendered}')
    return ';'.join(result)


class PrintFragment(HTMLParser):
    """Rebuild a printable fragment; only declared asset IDs can become images."""

    def __init__(self, assets: dict[str, str], preview: bool = False, visuals: dict | None = None):
        """Track allowed images, nesting, and all image references."""
        super().__init__(convert_charrefs=True)
        self.assets, self.preview = assets, preview
        self.visuals, self.used_visuals = visuals or {}, set()
        self.parts, self.stack, self.used = [], [], set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Validate tags and attributes and construct safe output markup."""
        tag = TAG_ALIASES.get(tag, tag)
        if tag not in TAGS:
            raise ValueError(f'Unsupported HTML tag: {tag}')
        data = dict(attrs)
        if len(data) != len(attrs) or set(data) - {'style', 'data-asset', 'data-visual', 'colspan', 'rowspan'}:
            raise ValueError('Only style, data-asset, data-visual, colspan and rowspan attributes are allowed')
        attributes = []
        if 'style' in data:
            attributes.append('style="' + html.escape(clean_style(data['style']), quote=True) + '"')
        for key in ('colspan', 'rowspan'):
            if key in data:
                if tag not in {'td', 'th'} or not re.fullmatch('[1-6]', data[key]):
                    raise ValueError('Invalid table span')
                attributes.append(f'{key}="{data[key]}"')
        if tag == 'img':
            asset, visual = data.get('data-asset'), data.get('data-visual')
            if bool(asset) == bool(visual):
                raise ValueError('An image needs exactly one data-asset or data-visual reference')
            if visual:
                if visual not in self.visuals:
                    raise ValueError('Unknown data-visual ID')
                self.used_visuals.add(visual)
                source = 'data:image/svg+xml;base64,' + base64.b64encode(self.visuals[visual][0].encode()).decode()
            else:
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
        elif 'data-asset' in data or 'data-visual' in data:
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
        """Repair harmless inline formatting mismatches; keep structural nesting strict."""
        tag = TAG_ALIASES.get(tag, tag)
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
            self.parts.append(f'</{tag}>')
            return
        if tag in INLINE_TAGS and tag in self.stack:
            position = len(self.stack) - 1 - self.stack[::-1].index(tag)
            intervening = self.stack[position + 1:]
            if all(open_tag in INLINE_TAGS for open_tag in intervening):
                for open_tag in reversed(intervening):
                    self.stack.pop()
                    self.parts.append(f'</{open_tag}>')
                self.stack.pop()
                self.parts.append(f'</{tag}>')
                return
        raise ValueError('HTML tags must be balanced and correctly nested')

    def handle_data(self, data: str) -> None:
        """Escape model-written text while preserving ordinary printable symbols."""
        self.parts.append(html.escape(data))


def fragment(page: dict, preview: bool = False) -> str:
    """Sanitize one authored page and require all declared artwork to be used."""
    assets = {a['id']: a.get('path', '') for a in page['images']}
    visuals = page_visuals(page)
    parser = PrintFragment(assets, preview, visuals)
    parser.feed(page['html'])
    parser.close()
    # Browsers safely auto-close trailing emphasis markup. Do the same only for
    # inline formatting tags; structural page markup remains strictly validated.
    while parser.stack and parser.stack[-1] in INLINE_TAGS:
        parser.parts.append(f'</{parser.stack.pop()}>')
    if parser.stack or parser.used != set(assets) or parser.used_visuals != set(visuals):
        raise ValueError('Close every HTML tag and use every declared illustration')
    mode = page.get('print_layout', '')
    classes = 'design'
    if mode in {'reflow', 'compact'}:
        classes += ' design-reflow'
    if mode == 'compact':
        classes += ' design-compact'
    return f'<div class="{classes}">' + ''.join(parser.parts) + '</div>'


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
    .store-logo {{height:36mm;overflow:hidden;text-align:center;margin-bottom:5mm;}}
    .store-logo img {{width:88mm;height:88mm;max-width:none;position:relative;top:-25mm;}}
    h4,h5,h6 {{font-size:1em;}}
    table {{width:100%;table-layout:fixed;}} td,th {{vertical-align:top;}}
    .design {{width:100%;overflow-wrap:anywhere;}}
    .design-reflow * {{box-sizing:border-box!important;min-width:0!important;max-width:100%!important;overflow-wrap:anywhere!important;}}
    .design-reflow table {{width:100%!important;table-layout:fixed!important;margin-left:0!important;margin-right:0!important;}}
    .design-reflow td,.design-reflow th {{width:auto!important;}}
    .design-compact p,.design-compact h1,.design-compact h2,.design-compact h3,
    .design-compact h4,.design-compact h5,.design-compact h6 {{margin-top:0!important;margin-bottom:2mm!important;}}
    .design-compact td,.design-compact th {{padding:2mm!important;}}
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


def _tighten_explicit_spacing(html_value: str) -> str:
    """Clamp excessive fixed spacing/heights as a last local fit attempt."""
    def replace(match):
        name = match.group(1).lower()
        value = float(match.group(2))
        unit = match.group(3).lower()
        if unit != 'mm':
            return match.group(0)
        limits = {
            'margin-top': 6, 'margin-bottom': 6, 'margin-left': 6, 'margin-right': 6,
            'padding-top': 6, 'padding-bottom': 6, 'padding-left': 6, 'padding-right': 6,
            'height': 90, 'min-height': 90, 'max-height': 120,
        }
        if name == 'margin':
            limit = 6
        elif name == 'padding':
            limit = 6
        else:
            limit = limits.get(name)
        if limit is None or value <= limit:
            return match.group(0)
        return f'{name}:{limit:g}mm'
    pattern = r'\b(margin(?:-(?:top|right|bottom|left))?|padding(?:-(?:top|right|bottom|left))?|height|min-height|max-height)\s*:\s*(\d+(?:\.\d+)?)(mm)\b'
    return re.sub(pattern, replace, html_value, flags=re.I)


def check_page(page: dict, font: int, *, cover: bool = False) -> None:
    """Try measured local reflow before requesting another model-authored design."""
    page.pop('print_layout', None)
    original_html = page['html']
    with RENDER_LOCK:
        for tightened in ((False,) if page.get('quality_profile') else (False, True)):
            if tightened:
                page['html'] = _tighten_explicit_spacing(original_html)
            for mode in ('', 'reflow', 'compact'):
                if mode:
                    page['print_layout'] = mode
                else:
                    page.pop('print_layout', None)
                markup = document_markup([cover_fragment(page, True) if cover else fragment(page, True)], font)
                doc = HTML(string=markup, url_fetcher=data_only_fetcher).render()
                try:
                    check_document(doc, 1)
                except ValueError:
                    continue
                check_visual_quality(doc, page.get('quality_profile', {}), cover=cover)
                return
        page['html'] = original_html
        page.pop('print_layout', None)
        raise ValueError('Design overflow: local reflow and deterministic spacing compaction could not fit the page')


def pack_markup(pack: dict, config: dict, preview: bool = False) -> str:
    """Compose model-authored pages and the single answer sheet for either render pass."""
    bodies = [cover_fragment(pack['cover'], preview)] + [fragment(p, preview) for p in pack['pages']]
    keys = ''.join(f'<section><h3>{i}. {html.escape(p["title"])}</h3><p>{html.escape(answer_text(p))}</p></section>' for i, p in enumerate(pack['pages'], 1))
    bodies.append('<h1>Answer Key</h1><p>Activity numbers match the student pages. Creative answers may vary.</p><div class="key">' + keys + '</div>')
    return document_markup(bodies, config.get('student_font_pt', 13))


def preflight_pack(pack: dict, config: dict) -> None:
    """Check the assembled book including the answer sheet before image API spending."""
    with RENDER_LOCK:
        doc = HTML(string=pack_markup(pack, config, preview=True), url_fetcher=data_only_fetcher).render()
        check_document(doc, len(pack['pages']) + 2)


def build_creative_pdf(pack: dict, config: dict, output_path: str | Path) -> Path:
    """Preserve AI-authored cover and student designs and append one compact answer key."""
    with RENDER_LOCK:
        doc = HTML(string=pack_markup(pack, config), url_fetcher=data_only_fetcher).render()
        check_document(doc, len(pack['pages']) + 2)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.write_pdf(str(target))
    return target


def check_visual_quality(document, profile: dict, *, cover: bool = False) -> None:
    """Measure actual image boxes and readable text in the laid-out student page."""
    if not profile:
        return
    area, largest = 0.0, 0.0
    for box in document.pages[0]._page_box.descendants():
        if box.element_tag == 'img' and hasattr(box, 'replacement'):
            value = box.width * box.height * (25.4 / 96) ** 2
            area += value
            largest = max(largest, value)
        if not cover and getattr(box, 'text', '').strip():
            if box.style['font_size'] * .75 + .01 < profile['minimum_text_pt']:
                raise ValueError(f"Student text is too small: use at least {profile['minimum_text_pt']}pt")
    # The cover includes the separately placed logo; student pages do not.
    minimum = profile['visual_area_mm2']
    if not cover and (area < minimum or largest < minimum * .55):
        raise ValueError(f'Visuals are too small: use at least {minimum:g} square mm of meaningful artwork/diagrams, '
                         'including one large main visual; preserve response space')
