"""Render AI-authored printable compositions inside a restricted HTML/CSS boundary."""
from __future__ import annotations

import base64
import html
import math
import re
from html.parser import HTMLParser
from pathlib import Path
from threading import RLock
from functools import lru_cache

import tinycss2
from weasyprint import HTML, default_url_fetcher
from core.paths import BASE_DIR
from core.print_tags import TAG_ALIASES
from core.content_binding import CanonicalTextContainers
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
INLINE_TAGS = {'span', 'strong', 'b', 'em'}
DROP_PROPERTIES = {'background-image', 'position', 'top', 'right', 'bottom', 'left', 'z-index', 'box-shadow', 'text-shadow'}
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


def clean_style(value: str, minimum_font: float = 11) -> str:
    """Allow print layout declarations, excluding resource loading and hidden content."""
    if re.search(r'[\\@<>]|url\s*\(|expression\s*\(|var\s*\(', value, re.I):
        raise ValueError('Unsupported CSS resource or expression')
    declarations = tinycss2.parse_declaration_list(value, skip_comments=True, skip_whitespace=True)
    result = []
    for decl in declarations:
        if decl.type != 'declaration':
            raise ValueError('Malformed inline CSS: use property:value declarations separated by semicolons')
        if decl.lower_name in {'overflow', 'overflow-x', 'overflow-y'}:
            # Visible is the print default; dropping it does not hide content.
            if tinycss2.serialize(decl.value).strip().lower() == 'visible':
                continue
            raise ValueError('CSS overflow may not hide, clip or scroll printable content; remove it')
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
            rendered = f'{max(minimum_font, min(40, points)):g}pt'
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


def reveal_print_content(markup: str) -> str:
    """Remove model-authored clipping declarations, then let measured bounds validate all content."""
    def replace(match):
        """Preserve other CSS declarations and escape the rebuilt attribute."""
        value = html.unescape(match[3])
        declarations = tinycss2.parse_declaration_list(value,skip_comments=True,skip_whitespace=True)
        if any(decl.type!='declaration' for decl in declarations):
            return match[0]  # Let the strict CSS validator report the original malformed syntax.
        kept,changed = [],False
        for decl in declarations:
            if decl.type=='declaration' and decl.lower_name in {'overflow','overflow-x','overflow-y'}:
                tokens = tinycss2.serialize(decl.value).strip().lower().split()
                if tokens and len(tokens)<=2 and set(tokens)<={'visible','hidden','clip','auto','scroll'}:
                    changed = True
                    continue  # Normal document flow exposes all content; never hides it.
            kept.append(decl)
        if not changed: return match[0]
        return match[1]+match[2]+html.escape(tinycss2.serialize(kept),quote=True)+match[2]
    return re.sub(r"(\bstyle\s*=\s*)(['\"])(.*?)\2",replace,markup,flags=re.I|re.S)


class PrintFragment(HTMLParser):
    """Rebuild a printable fragment; only declared asset IDs can become images."""

    def __init__(self, assets: dict[str, str], preview: bool = False, visuals: dict | None = None, minimum_font: float = 11):
        """Track allowed images, nesting, and all image references."""
        super().__init__(convert_charrefs=True)
        self.assets, self.preview = assets, preview
        self.minimum_font = minimum_font
        self.visuals, self.used_visuals = visuals or {}, set()
        self.parts, self.stack, self.used = [], [], set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Validate tags and attributes and construct safe output markup."""
        tag = TAG_ALIASES.get(tag, tag)
        if tag not in TAGS:
            raise ValueError(f'Unsupported HTML tag: {tag}')
        data = dict(attrs)
        if len(data) != len(attrs):
            raise ValueError(f'Duplicate print attributes on <{tag}>')
        unknown = set(data) - {'style', 'data-asset', 'data-visual', 'colspan', 'rowspan'}
        if unknown:
            raise ValueError(f'Unsupported print attributes {sorted(unknown)} on <{tag}>; '
                             'use only style, data-asset, data-visual, colspan and rowspan')
        attributes = []
        if 'style' in data:
            attributes.append('style="' + html.escape(clean_style(data['style'], self.minimum_font), quote=True) + '"')
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
            from core.image_dimensions import length_mm
            declarations = tinycss2.parse_declaration_list(clean_style(data.get('style',''),self.minimum_font),skip_comments=True,skip_whitespace=True)
            sizes = {d.lower_name:tinycss2.serialize(d.value).strip() for d in declarations if d.lower_name in {'height','width'}}
            height = length_mm(sizes.get('height',''))
            width = length_mm(sizes.get('width',''))
            percent = re.fullmatch(r'(\d+(?:\.\d+)?|\.\d+)%',sizes.get('width',''))
            if height is None or height<=0:
                raise ValueError('Every image needs an explicit positive height in mm')
            if not ((width is not None and width>0) or (percent and float(percent[1])>0)):
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
    parser = PrintFragment(assets, preview, visuals, page.get('quality_profile', {}).get('minimum_text_pt', 11))
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
    from core.print_collisions import check_print_collisions
    check_print_collisions(document)
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


def _tighten_explicit_spacing(html_value: str, *, preserve_heights: bool = False) -> str:
    """Clamp excessive spacing; preserve response and illustration heights on quality pages."""
    def replace(match):
        name = match.group(1).lower()
        value = float(match.group(2))
        unit = match.group(3).lower()
        if unit != 'mm' or (preserve_heights and 'height' in name):
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


def reflow_outer_panels(markup: str) -> str:
    """Remove redundant wrapper heights only around artwork and an explicit canonical work area."""
    parser = CanonicalTextContainers({})
    parser.feed(markup); parser.close()
    if parser.stack: return markup
    changed = False

    def inspect(node):
        """Find real media and independently dimensioned response space without editing either."""
        nonlocal changed
        if isinstance(node,str) or 'comment' in node: return False,False
        flags = [inspect(child) for child in node['children']]
        data = dict(node['attrs'])
        style = data.get('style','') or ''
        art = node['tag']=='img' and bool(data.get('data-asset') or data.get('data-visual'))
        response = (node['tag']=='span' and 'height:' in style and
                    re.search(r'border\s*:\s*0\.4mm\s+solid\s+#809aa6',style,re.I) is not None)
        child_art = any(a for a,_ in flags)
        child_response = any(r for _,r in flags)
        if node['tag'] in {'div','section','table','td'} and child_art and child_response:
            cleaned = re.sub(r'(?:^|;)\s*(?:height|min-height|max-height)\s*:[^;]*(?:;|$)', ';',style,flags=re.I)
            # A second adjacent dimension can follow the first replaced separator.
            cleaned = re.sub(r'(?:^|;)\s*(?:height|min-height|max-height)\s*:[^;]*(?:;|$)', ';',cleaned,flags=re.I)
            if cleaned!=style:
                node['attrs'] = [(key,cleaned if key=='style' else value) for key,value in node['attrs']]
                changed = True
        return art or child_art,response or child_response

    def render(node):
        """Serialize the retained tree without canonical-slot inference or dropping any content."""
        if isinstance(node,str): return html.escape(node,quote=False)
        if 'comment' in node: return '<!--'+node['comment']+'-->'
        attrs = ' '.join(f'{key}="{html.escape(value or "",quote=True)}"' for key,value in node['attrs'])
        start = f'<{node["tag"]} {attrs}>'
        if node['tag'] in {'img','br'}: return start
        return start+''.join(render(child) for child in node['children'])+f'</{node["tag"]}>'

    for node in parser.root: inspect(node)
    return ''.join(render(node) for node in parser.root) if changed else markup


def grow_main_artwork(markup: str, document, profile: dict) -> str | None:
    """Recover modest area shortfalls without upscaling thumbnails or changing task content."""
    areas = [box.width*box.height*(25.4/96)**2 for box in document.pages[0]._page_box.descendants()
             if box.element_tag=='img' and hasattr(box,'replacement')]
    if not areas: return None
    minimum = profile['visual_area_mm2']
    from core.visual_area import sufficient_visual_area
    if sufficient_visual_area(areas,minimum): return None
    candidates = []
    for match in re.finditer(r'<img\b[^>]*>',markup,re.I):
        tag = match[0]
        if not re.search(r'\bdata-(?:asset|visual)\s*=',tag,re.I): continue
        width = re.search(r'(?<!-)\bwidth\s*:\s*([0-9.]+)mm',tag,re.I)
        height = re.search(r'(?<!-)\bheight\s*:\s*([0-9.]+)mm',tag,re.I)
        if width and height:
            w,h = float(width[1]),float(height[1])
            if w>0 and h>0: candidates.append((w*h,match,w,h))
    if not candidates: return None
    _,match,w,h = max(candidates,key=lambda entry:entry[0])
    measured = max(areas)
    target = max(measured+max(0,minimum-sum(areas)),minimum*.55)
    scale = math.sqrt(target/measured)*1.015
    if not 1<scale<=2 or w*scale>180 or h*scale>160: return None
    tag = re.sub(r'(?<!-)\bwidth\s*:\s*[0-9.]+mm',f'width:{w*scale:.2f}mm',match[0],flags=re.I)
    tag = re.sub(r'(?<!-)\bheight\s*:\s*[0-9.]+mm',f'height:{h*scale:.2f}mm',tag,flags=re.I)
    return markup[:match.start()]+tag+markup[match.end():]


def check_page(page: dict, font: int, *, cover: bool = False, _allow_growth: bool = True) -> None:
    """Try measured local reflow before requesting another model-authored design."""
    page.pop('print_layout', None)
    from core.image_dimensions import normalize_image_dimensions
    profile = page.get('quality_profile', {})
    page['html'] = normalize_image_dimensions(page['html'],page_visuals(page),
        profile.get('visual_area_mm2',6500),lambda style:clean_style(style,profile.get('minimum_text_pt',11)))
    original_html = page['html']
    last_overflow = ''
    rendered_markup = set()
    with RENDER_LOCK:
        tightened_html = _tighten_explicit_spacing(original_html, preserve_heights=bool(page.get('quality_profile')))
        panel_html = reflow_outer_panels(tightened_html) if page.get('exercise_binding') else tightened_html
        candidates = list(dict.fromkeys((original_html,tightened_html,panel_html)))
        overflow_recovered = False
        for candidate_html in candidates:
            page['html'] = candidate_html
            for mode in ('', 'reflow', 'compact'):
                if mode:
                    page['print_layout'] = mode
                else:
                    page.pop('print_layout', None)
                markup = document_markup([cover_fragment(page, True) if cover else fragment(page, True)], font)
                if markup in rendered_markup:
                    continue  # Unchanged spacing does not need three identical renders again.
                rendered_markup.add(markup)
                doc = HTML(string=markup, url_fetcher=data_only_fetcher).render()
                try:
                    check_document(doc, 1)
                except ValueError as exc:
                    last_overflow = str(exc)
                    if not cover and not overflow_recovered:
                        from core.small_overflow import recover_small_overflow
                        resized = recover_small_overflow(page['html'], doc, profile)
                        if resized:
                            candidates.append(resized)
                            overflow_recovered = True
                    continue
                try:
                    check_visual_quality(doc, page.get('quality_profile', {}), cover=cover)
                except ValueError as quality_error:
                    if not cover and _allow_growth and str(quality_error).startswith('Visuals are too small'):
                        grown = grow_main_artwork(page['html'],doc,page['quality_profile'])
                        if grown:
                            retained_html, retained_mode = page['html'],page.get('print_layout')
                            page['html'] = grown
                            try:
                                check_page(page,font,cover=cover,_allow_growth=False)
                                return
                            except ValueError:
                                page['html'] = retained_html
                                if retained_mode: page['print_layout'] = retained_mode
                                else: page.pop('print_layout',None)
                    raise quality_error
                return
        page['html'] = original_html
        page.pop('print_layout', None)
        raise ValueError('Design overflow: local reflow and spacing compaction could not fit the page. '
                         + last_overflow + '. Keep grade-specific minimum font sizes; shorten directions '
                         'or reorganize panels instead of reducing text or response space.')


def answer_key_markup(pack: dict, mode: str = 'standard') -> str:
    """Render every canonical answer, varying only final-sheet typography and spacing."""
    if mode not in {'standard','compact','dense'}:
        raise ValueError('Unknown answer sheet layout')
    compact = mode != 'standard'
    font = 9.5 if mode == 'dense' else 10
    section_style = ('margin:0 0 2mm;border-top:0.5mm solid #188a91;padding-top:1mm' if compact else '')
    heading_style = 'font-size:10pt;margin:0 0 1mm;line-height:1.15' if compact else ''
    paragraph_style = f'font-size:{font:g}pt;margin:0;line-height:1.2;overflow-wrap:anywhere' if compact else ''
    sections = []
    for i, page in enumerate(pack['pages'], 1):
        if pack.get('content_format') == 'reading_qcm' and page.get('page_type') != 'qcm':
            continue
        label = 'PDF page '+str(i+1) if pack.get('content_format') == 'reading_qcm' else str(i)
        heading = f'<h3 style="{heading_style}">{label}. {html.escape(page["title"])}</h3>'
        items = page.get('answer_items')
        if pack.get('content_format') == 'reading_qcm' and items:
            content = ''.join(
                f'<p style="font-size:{font:g}pt;margin:0 0 1.5mm;line-height:1.2">'
                f'<strong>{item["number"]}. {html.escape(item["answer"])}:</strong> '
                f'{html.escape(item["explanation"])}</p>' for item in items)
        else:
            content = f'<p style="{paragraph_style}">{html.escape(answer_text(page))}</p>'
        sections.append(f'<section style="{section_style}">{heading}{content}</section>')
    keys = ''.join(sections)
    intro_style = 'font-size:10pt;margin-bottom:3mm' if compact else ''
    intro = ('PDF page numbers identify the question pages. Each question has one correct answer.'
             if pack.get('content_format') == 'reading_qcm'
             else 'Activity numbers match the student pages. Creative answers may vary.')
    return ('<h1>Answer Key</h1>'
            f'<p style="{intro_style}">{intro}</p>'
            '<div class="key">'+keys+'</div>')


def fit_answer_key(pack: dict, config: dict) -> None:
    """Select a measured one-page key layout without rewriting or deleting any answers."""
    with RENDER_LOCK:
        for mode in ('standard','compact','dense'):
            doc = HTML(string=document_markup([answer_key_markup(pack,mode)],config.get('student_font_pt',13)),
                       url_fetcher=data_only_fetcher).render()
            try:
                check_document(doc,1)
            except ValueError:
                continue
            pack['answer_key_layout'] = mode
            return
    raise ValueError('Final answer sheet cannot fit one A4 page with readable text. '
                     'Shorten the shared question answer/criterion fields while retaining every solution; '
                     'student activities and images do not need redesign.')


def pack_markup(pack: dict, config: dict, preview: bool = False) -> str:
    """Compose model-authored pages and the measured single answer sheet for both render passes."""
    bodies = [cover_fragment(pack['cover'], preview)] + [fragment(p, preview) for p in pack['pages']]
    bodies.append(answer_key_markup(pack,pack.get('answer_key_layout','standard')))
    return document_markup(bodies, config.get('student_font_pt', 13))


def preflight_pack(pack: dict, config: dict) -> None:
    """Measure the final key and assembled book before any image API spending."""
    with RENDER_LOCK:
        fit_answer_key(pack,config)
        doc = HTML(string=pack_markup(pack, config, preview=True), url_fetcher=data_only_fetcher).render()
        check_document(doc, len(pack['pages']) + 2)


def build_creative_pdf(pack: dict, config: dict, output_path: str | Path) -> Path:
    """Preserve AI-authored cover and student designs and append one compact answer key."""
    with RENDER_LOCK:
        if 'answer_key_layout' not in pack:
            fit_answer_key(pack,config)
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
    from core.visual_area import sufficient_visual_area
    area, largest = 0.0, 0.0
    areas = []
    for box in document.pages[0]._page_box.descendants():
        if box.element_tag == 'img' and hasattr(box, 'replacement'):
            value = box.width * box.height * (25.4 / 96) ** 2
            areas.append(value)
            area += value
            largest = max(largest, value)
        if not cover and getattr(box, 'text', '').strip():
            if box.style['font_size'] * .75 + .01 < profile['minimum_text_pt']:
                raise ValueError(f"Student text is too small: use at least {profile['minimum_text_pt']}pt")
    # The cover includes the separately placed logo; student pages do not.
    minimum = profile['visual_area_mm2']
    if not cover and minimum > 0 and not sufficient_visual_area(areas, minimum):
        raise ValueError(f'Visuals are too small: use at least {minimum:g} square mm of meaningful artwork/diagrams, '
                         f'including one large main visual of at least {minimum*.55:g} square mm '
                         'or 2-4 substantial panels (each at least 75% of an equal share of the total target); '
                         f'measured total {area:.0f} square mm and largest visual {largest:.0f} square mm. '
                         'Preserve response space')

