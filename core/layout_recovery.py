"""Lossless recovery layouts for already valid single-illustration exercise content."""
from copy import deepcopy
import math
import re

from core.page_contract import compile_exercise
from core.content_binding import CanonicalTextContainers


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
