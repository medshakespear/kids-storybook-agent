"""Lossless recovery layouts for already valid single-illustration exercise content."""
from copy import deepcopy
import math
import re

from core.page_contract import compile_exercise
from core.content_binding import CanonicalTextContainers


def single_exact_visual_recovery(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Recompose one valid computed diagram at its true aspect ratio and readable scale."""
    if (not isinstance(page,dict) or not isinstance(page.get('exercise'),dict)
            or page['exercise'].get('render_mode')!='exact' or page.get('images') not in ([],None)
            or not 0<visual_area<=22000):
        return None
    checked=deepcopy(page)
    try:
        compile_exercise(checked,{'student_font_pt':minimum_font,'minimum_text_pt':minimum_font,
                                 'items_per_page':16},'Internal layout check',defer_visual_sizing=True)
        from core.task_visuals import page_visuals
        visuals=page_visuals(checked)
        if len(visuals)!=1:
            return None
        parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
        def untracked(node):
            """Do not discard independent dimensioned empty working panels."""
            if isinstance(node,str) or 'comment' in node:
                return False
            attrs=dict(node['attrs'])
            empty=not any(isinstance(c,dict) or c.strip() for c in node['children'])
            sized=re.search(r'(?:^|;)\s*(?:height|min-height)\s*:\s*[1-9][0-9.]*',attrs.get('style',''))
            if node['tag'] not in {'img','br'} and not attrs.get('data-content') and empty and sized:
                return True
            return any(untracked(c) for c in node['children'])
        if any(untracked(node) for node in parser.root):
            return None
    except (ValueError,TypeError,KeyError,IndexError):
        return None
    vid,(svg,_)=next(iter(visuals.items()))
    width=float(re.search(r'<svg[^>]*width="([0-9.]+)"',svg)[1])
    height=float(re.search(r'<svg[^>]*height="([0-9.]+)"',svg)[1])
    smallest=min(float(v) for v in re.findall(r'font-size="([0-9.]+)"',svg))
    scale=max(math.sqrt(visual_area/(width*height)),minimum_font*25.4/(72*smallest))*1.02
    w,h=math.ceil(width*scale),math.ceil(height*scale)
    if w>175 or h>185:
        return None
    colors=re.findall(r'#[0-9a-fA-F]{6}\b',page['html'])
    accent=colors[0] if colors else '#167E80'
    wash=next((c for c in colors[1:] if c.lower()!=accent.lower()),'#EAF5F2')
    pieces=[f'<h1 data-content="title" style="font-size:{minimum_font+5}pt;color:{accent};'
            f'background-color:{wash};padding:3mm;border-radius:4mm;margin:0 0 3mm"></h1>',
            f'<p data-content="name" style="font-size:{minimum_font}pt;margin:0 0 2mm"></p>']
    if re.search(r'Date:\s*_+',checked['html']):
        pieces.append(f'<p data-content="date" style="font-size:{minimum_font}pt;margin:0 0 2mm"></p>')
    for caption in checked['exercise'].get('captions',[]):
        pieces.append(f'<p data-content="caption_{caption["id"]}" style="font-size:{minimum_font}pt;margin:0 0 2mm"></p>')
    pieces.append(f'<div style="text-align:center;margin:0 0 3mm"><img data-visual="{vid}" '
                  f'style="width:{w}mm;height:{h}mm"/></div>')
    for question in checked['exercise'].get('questions',[]):
        pieces.append(f'<div data-content="question_{question["id"]}" style="font-size:{minimum_font}pt;'
                      'padding:1mm;margin:0 0 3mm"></div>')
    result=deepcopy(page);result['exercise']=deepcopy(checked['exercise']);result['html']=''.join(pieces)
    return result


def single_illustration_recovery(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Recompose one artwork and canonical tasks; never omit unbound text or shrink work space."""
    if not isinstance(page,dict) or not isinstance(page.get('exercise'),dict):
        return None
    if page['exercise'].get('render_mode')!='authored':
        return None
    images = page.get('images')
    if not isinstance(images,list) or len(images)!=1 or not isinstance(images[0],dict):
        return None
    asset = images[0].get('id')
    if not isinstance(asset,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,30}',asset):
        return None
    # Verify the retained source binds every word before recomposition. A malformed
    # caption or additional task cannot be discarded to make a layout fit.
    checked = deepcopy(page)
    try:
        compile_exercise(checked,{'student_font_pt':minimum_font,'minimum_text_pt':minimum_font,
                                 'items_per_page':16},'Internal layout check')
        parser = CanonicalTextContainers({})
        parser.feed(page['html']);parser.close()
        def untracked_space(node):
            """Keep unidentified blank working panels out of the local recomposition path."""
            if isinstance(node,str) or 'comment' in node:
                return False
            attrs = dict(node['attrs'])
            empty = not any(isinstance(c,dict) or c.strip() for c in node['children'])
            sized = re.search(r'(?:^|;)\s*(?:height|min-height)\s*:\s*[1-9][0-9.]*',attrs.get('style',''))
            if node['tag'] not in {'img','br'} and not attrs.get('data-content') and empty and sized:
                return True
            return any(untracked_space(c) for c in node['children'])
        if any(untracked_space(node) for node in parser.root):
            return None
    except (ValueError,TypeError,KeyError,IndexError):
        return None
    if not 0<visual_area<=22000:
        return None
    side = math.ceil(math.sqrt(visual_area)*1.02)
    if side>155:
        return None
    colors = re.findall(r'#[0-9a-fA-F]{6}\b',page['html'])
    accent = colors[0] if colors else '#167E80'
    wash = next((c for c in colors[1:] if c.lower()!=accent.lower()),'#EAF5F2')
    exercise = checked['exercise']
    pieces = [f'<h1 data-content="title" style="font-size:{minimum_font+5}pt;color:{accent};'
              f'background-color:{wash};padding:3mm;border-radius:4mm;margin:0 0 3mm"></h1>',
              f'<p data-content="name" style="font-size:{minimum_font}pt;margin:0 0 2mm"></p>',
              f'<p data-content="directions" style="font-size:{minimum_font}pt;margin:0 0 3mm"></p>']
    for caption in exercise.get('captions',[]):
        pieces.append(f'<p data-content="caption_{caption["id"]}" style="font-size:{minimum_font}pt;'
                      f'color:{accent};margin:0 0 2mm"></p>')
    if re.search(r'Date:\s*_+',checked['html']):
        pieces.append(f'<p data-content="date" style="font-size:{minimum_font}pt;margin:0 0 2mm"></p>')
    pieces.append(f'<div style="text-align:center;background-color:{wash};padding:2mm;'
                  f'border:0.5mm solid {accent};border-radius:4mm;margin:0 0 3mm">'
                  f'<img data-asset="{asset}" style="width:{side}mm;height:{side}mm"/></div>')
    if exercise.get('passage'):
        pieces.append(f'<div data-content="passage" style="font-size:{minimum_font}pt;margin:0 0 3mm"></div>')
    for question in exercise.get('questions',[]):
        pieces.append(f'<div data-content="question_{question["id"]}" style="font-size:{minimum_font}pt;'
                      f'padding:1mm;border-top:0.5mm solid {accent};margin:0 0 3mm"></div>')
    result = deepcopy(page)
    result['exercise'] = deepcopy(exercise)
    result['html'] = ''.join(pieces)
    return result


def multiple_illustration_recovery(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Recompose all declared artwork and canonical text without deleting an exercise asset."""
    images = page.get('images') if isinstance(page, dict) else None
    if not isinstance(images, list) or not 2 <= len(images) <= 4:
        return None
    # The single-artwork safety pass checks bindings and independent response panels.
    probe = deepcopy(page)
    if not isinstance(probe.get('exercise'), dict) or probe['exercise'].get('render_mode') != 'authored':
        return None
    try:
        compile_exercise(probe, {'student_font_pt':minimum_font, 'minimum_text_pt':minimum_font,
                                'items_per_page':16}, 'Internal layout check')
        parser = CanonicalTextContainers({}); parser.feed(page['html']); parser.close()
        def untracked(node):
            """Refuse to drop blank working panels that are outside the canonical questions."""
            if isinstance(node, str) or 'comment' in node:
                return False
            attrs = dict(node['attrs'])
            empty = not any(isinstance(c, dict) or c.strip() for c in node['children'])
            sized = re.search(r'(?:^|;)\s*(?:height|min-height)\s*:\s*[1-9][0-9.]*', attrs.get('style',''))
            if node['tag'] not in {'img','br'} and not attrs.get('data-content') and empty and sized:
                return True
            return any(untracked(c) for c in node['children'])
        if any(untracked(n) for n in parser.root):
            return None
        for image in images:
            if not isinstance(image, dict) or not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', str(image.get('id',''))):
                return None
        # Generate text layout using the same lossless safety path; strip only the
        # other known image slots in this temporary probe, never tasks or wording.
        probe = deepcopy(page)
        ids = [image['id'] for image in images]
        probe['html'] = re.sub(r'<img\b[^>]*\bdata-asset=[\'\"]([^\'\"]+)[\'\"][^>]*>',
                              lambda m: m[0] if m[1] == ids[0] else '', probe['html'], flags=re.I)
        probe['images'] = [deepcopy(images[0])]
        base = single_illustration_recovery(probe, minimum_font, visual_area)
        if base is None:
            return None
        # A large primary visual plus a vertical rail preserves all artwork,
        # provides a meaningful main visual, and fits the 186mm content width.
        main_height = max(65, math.ceil(visual_area / 130 * 1.02))
        rail_height = max(24, min(35, main_height // (len(ids)-1)))
        if main_height > 150:
            return None
        rail = ''.join(f'<img data-asset="{aid}" style="display:block;width:38mm;height:{rail_height}mm;margin:0 0 2mm"/>'
                       for aid in ids[1:])
        gallery = ('<table style="width:175mm;table-layout:fixed;border-spacing:0;margin:0 0 3mm"><tbody><tr>'
                   f'<td style="width:130mm;padding:0;vertical-align:middle"><img data-asset="{ids[0]}" '
                   f'style="width:130mm;height:{main_height}mm"/></td>'
                   f'<td style="width:45mm;padding:0;vertical-align:middle">{rail}</td></tr></tbody></table>')
        base['html'] = re.sub(r'<div style="text-align:center;background-color:[^>]*>\s*<img[^>]*>\s*</div>',
                              lambda m: gallery, base['html'], count=1)
        base['images'] = deepcopy(images)
        if set(re.findall(r'data-asset="([^"]+)"',base['html'])) != set(ids):
            return None
        return base
    except (ValueError, TypeError, KeyError, IndexError):
        return None


def reading_panel_recovery(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Place supporting reading beside artwork, retaining full-width response areas."""
    exercise = page.get('exercise', {}) if isinstance(page, dict) else {}
    if not isinstance(exercise, dict):
        return None
    captions = exercise.get('captions', [])
    if not (exercise.get('passage') or (isinstance(captions, list) and len(captions) >= 2)):
        return None
    # Reuse the lossless binding and untracked-workspace safety checks before
    # changing composition. This is an alternative layout, never a content edit.
    base = single_illustration_recovery(page, minimum_font, visual_area)
    if base is None:
        return None
    exercise = base['exercise']
    asset = base['images'][0]['id']
    colors = re.findall(r'#[0-9a-fA-F]{6}\b', page['html'])
    accent = colors[0] if colors else '#167E80'
    wash = colors[1] if len(colors) > 1 else '#EAF5F2'
    height = math.ceil(visual_area * 1.04 / 100)
    if height > 150:
        return None
    text_style = f'font-size:{minimum_font}pt;line-height:1.2;margin:0 0 2mm'
    pieces = [f'<h1 data-content="title" style="font-size:{minimum_font+5}pt;color:{accent};'
              f'background-color:{wash};padding:3mm;margin:0 0 3mm"></h1>',
              f'<p data-content="name" style="{text_style}"></p>']
    if re.search(r'Date:\s*_+', base['html']):
        pieces.append(f'<p data-content="date" style="{text_style}"></p>')
    supporting = [f'<p data-content="directions" style="{text_style}"></p>']
    if exercise.get('passage'):
        supporting.append(f'<div data-content="passage" style="{text_style}"></div>')
    for caption in exercise.get('captions', []):
        supporting.append(f'<p data-content="caption_{caption["id"]}" style="{text_style}"></p>')
    pieces.append('<table style="width:175mm;table-layout:fixed;border-spacing:0;margin:0 0 3mm"><tbody><tr>'
                  f'<td style="width:100mm;padding:0;vertical-align:top"><img data-asset="{asset}" '
                  f'style="width:100mm;height:{height}mm"/></td>'
                  '<td style="width:75mm;padding:0 0 0 3mm;vertical-align:top">' + ''.join(supporting) +
                  '</td></tr></tbody></table>')
    for question in exercise.get('questions', []):
        pieces.append(f'<div data-content="question_{question["id"]}" style="{text_style};'
                      f'padding:1mm;border-top:0.5mm solid {accent}"></div>')
    result = deepcopy(base)
    result['html'] = ''.join(pieces)
    return result


def layout_recovery_candidates(page: dict, minimum_font: int, visual_area: float):
    """Try bounded lossless compositions with sufficient art before another model rewrite."""
    single = single_illustration_recovery(page,minimum_font,visual_area)
    if single is not None:
        yield single
        asset = single['images'][0]['id']
        # A square main-art panel wastes vertical space on reading/response-heavy
        # sheets. Wider panels retain the same asset, full-width response areas,
        # uncropped fitting, and at least the required measured artwork area.
        for width in (175,150):
            height = math.ceil(visual_area*1.04/width)
            candidate = deepcopy(single)
            pattern = r'(<img\b[^>]*data-asset="'+re.escape(asset)+r'"[^>]*style=")[^"]*("[^>]*>)'
            candidate['html'] = re.sub(pattern,lambda m:m[1]+f'width:{width}mm;height:{height}mm'+m[2],candidate['html'],count=1)
            yield candidate
    multiple = multiple_illustration_recovery(page,minimum_font,visual_area)
    if multiple is not None:
        from core.illustration_gallery import illustration_gallery, gallery_minimum_height
        balanced = deepcopy(multiple)
        ids = [image['id'] for image in multiple['images']]
        gallery = illustration_gallery(ids,gallery_minimum_height(len(ids),visual_area))
        balanced['html'] = re.sub(r'<table style="width:175mm;table-layout:fixed;border-spacing:0;margin:0 0 3mm">.*?</table>',
                                 lambda match:gallery,balanced['html'],count=1,flags=re.S)
        yield balanced
        yield multiple
    reading = reading_panel_recovery(page,minimum_font,visual_area)
    if reading is not None:
        yield reading
    exact = single_exact_visual_recovery(page,minimum_font,visual_area)
    if exact is not None:
        yield exact

