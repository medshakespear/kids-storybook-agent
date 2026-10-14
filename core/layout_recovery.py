"""Lossless recovery layouts for already valid single-illustration exercise content."""
from copy import deepcopy
import html
import math
import re

from core.page_contract import compile_exercise
from core.content_binding import CanonicalTextContainers, canonical_content_slot
from html.parser import HTMLParser


def recovery_profile(page: dict, minimum_font: int) -> dict:
    """Use the real mixed grade contract when it was retained by the validator."""
    return deepcopy(page.get('_recovery_config') or {
        'student_font_pt':minimum_font,'minimum_text_pt':minimum_font,'items_per_page':16})


def supporting_slot_ids(page: dict, exercise: dict) -> list[str]:
    """Retain source/caption order without inferring or changing wording."""
    available = {'passage':True} if exercise.get('passage') else {}
    for field,prefix in (('captions','caption_'),('stimuli','stimulus_')):
        for item in exercise.get(field,[]):
            available[prefix+item['id']] = True
    ordered=[]
    parser=HTMLParser(convert_charrefs=True)
    def collect(tag,attrs):
        """Read declared canonical slot order from the model's retained composition."""
        slot=canonical_content_slot(dict(attrs).get('data-content'),available)
        if slot in available and slot not in ordered:
            ordered.append(slot)
    parser.handle_starttag=collect
    parser.handle_startendtag=collect
    parser.feed(page['html']);parser.close()
    return ordered+[slot for slot in available if slot not in ordered]


def readable_exact_layout(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Resize one verified SVG in the retained layout using its actual smallest label.

    Keep every wrapper, caption, question and writing panel. The caller still
    measures page fit; expanding artwork in a narrow column cannot bypass it.
    """
    if (not isinstance(page.get('exercise'),dict)
            or page['exercise'].get('render_mode') != 'exact' or not 0 < visual_area <= 22000):
        return None
    checked=deepcopy(page)
    try:
        compile_exercise(checked,recovery_profile(page,minimum_font),
                         page.get('_recovery_title','Internal layout check'),defer_visual_sizing=True)
        from core.task_visuals import page_visuals
        visuals=page_visuals(checked)
        if len(visuals) != 1:
            return None
        vid,(svg,_) = next(iter(visuals.items()))
        width=float(re.search(r'<svg[^>]*width="([0-9.]+)"',svg)[1])
        height=float(re.search(r'<svg[^>]*height="([0-9.]+)"',svg)[1])
        smallest=min(float(v) for v in re.findall(r'font-size="([0-9.]+)"',svg))
        scale=max(math.sqrt(visual_area/(width*height)),minimum_font*25.4/(72*smallest))*1.02
        w,h=math.ceil(width*scale),math.ceil(height*scale)
        if w > 180 or h > 230:
            return None
        parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
        targets=[]

        def visit(node):
            """Locate only the single declared graphic, leaving other dimensions untouched."""
            if isinstance(node,str) or 'comment' in node:
                return
            if node['tag']=='img' and dict(node['attrs']).get('data-visual')==vid:
                targets.append(node)
            for child in node['children']:
                visit(child)

        for node in parser.root:
            visit(node)
        if parser.stack or len(targets)!=1:
            return None
        target=targets[0];style=dict(target['attrs']).get('style','')
        # Remove only image size constraints; preserve its display, color and
        # spacing. No other content or response dimension is changed.
        style=re.sub(r'(?:^|;)\s*(?:width|height|min-width|max-width|min-height|max-height)\s*:[^;]*', '',style,flags=re.I).strip('; ')
        style += f';width:{w}mm;height:{h}mm'
        target['attrs']=[(k,v) for k,v in target['attrs'] if k!='style']+[('style',style)]

        def literal(node):
            """Serialize without inferring text bindings or dropping raw metadata."""
            if isinstance(node,str):
                return html.escape(node,quote=False)
            if 'comment' in node:
                return '<!--'+node['comment']+'-->'
            attrs=' '.join(f'{k}="{html.escape(v or "",quote=True)}"' for k,v in node['attrs'])
            start=f'<{node["tag"]} {attrs}>'
            return start if node['tag'] in {'img','br'} else start+''.join(literal(c) for c in node['children'])+f'</{node["tag"]}>'

        result=deepcopy(page)
        result['html']=''.join(literal(node) for node in parser.root)
        return result
    except (ValueError,TypeError,KeyError,IndexError,ZeroDivisionError):
        return None


def single_exact_visual_recovery(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Recompose one valid computed diagram at its true aspect ratio and readable scale."""
    if (not isinstance(page,dict) or not isinstance(page.get('exercise'),dict)
            or page['exercise'].get('render_mode')!='exact' or page.get('images') not in ([],None)
            or not 0<visual_area<=22000):
        return None
    from core.missing_exact_context import recover_missing_exact_context
    checked=recover_missing_exact_context(page)
    try:
        compile_exercise(checked,recovery_profile(page,minimum_font),
                         page.get('_recovery_title','Internal layout check'),defer_visual_sizing=True)
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
    if w>180 or h>185:
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


def exact_caption_grid_recovery(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Arrange contextual labels in two columns without resizing the exact puzzle or work areas."""
    base = single_exact_visual_recovery(page, minimum_font, visual_area)
    if base is None:
        return None
    captions = base['exercise'].get('captions', [])
    if len(captions) < 2:
        return None
    style = f'font-size:{minimum_font}pt;line-height:1.2;margin:0'
    rows = []
    for offset in range(0, len(captions), 2):
        cells = ''.join(f'<td style="width:87.5mm;padding:1mm;vertical-align:top">'
                        f'<p data-content="caption_{caption["id"]}" style="{style}"></p></td>'
                        for caption in captions[offset:offset+2])
        if offset + 1 == len(captions):
            cells += '<td style="width:87.5mm;padding:1mm"></td>'
        rows.append('<tr>' + cells + '</tr>')
    grid = '<table style="width:175mm;table-layout:fixed;border-spacing:0;margin:0 0 2mm"><tbody>' + ''.join(rows) + '</tbody></table>'
    pattern = r'<p data-content="caption_[a-z][a-z0-9_]*" style="[^"]*"></p>'
    matches = list(re.finditer(pattern, base['html']))
    if len(matches) != len(captions):
        return None
    first = matches[0].start()
    # Only replace the contiguous caption sequence emitted by our own safe
    # layout; never collect text from arbitrary author HTML or puzzle artwork.
    end = matches[-1].end()
    if re.sub(pattern, '', base['html'][first:end]).strip():
        return None
    result = deepcopy(base)
    result['html'] = base['html'][:first] + grid + base['html'][end:]
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
        compile_exercise(checked,recovery_profile(page,minimum_font),page.get('_recovery_title') or 'Internal layout check')
        if checked.get('_table_caption_ids'):
            return None  # Flattening data-table cells would destroy their row/column relationships.
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
    for slot in supporting_slot_ids(page,exercise):
        pieces.append(f'<p data-content="{slot}" style="font-size:{minimum_font}pt;color:{accent};margin:0 0 2mm"></p>')
    if re.search(r'Date:\s*_+',checked['html']):
        pieces.append(f'<p data-content="date" style="font-size:{minimum_font}pt;margin:0 0 2mm"></p>')
    pieces.append(f'<div style="text-align:center;background-color:{wash};padding:2mm;'
                  f'border:0.5mm solid {accent};border-radius:4mm;margin:0 0 3mm">'
                  f'<img data-asset="{asset}" style="width:{side}mm;height:{side}mm"/></div>')

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
        compile_exercise(probe,recovery_profile(page,minimum_font),page.get('_recovery_title') or 'Internal layout check')
        if probe.get('_table_caption_ids'):
            return None
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
    """Place supporting reading beside all artwork, retaining full-width response areas."""
    exercise = page.get('exercise', {}) if isinstance(page, dict) else {}
    if not isinstance(exercise, dict):
        return None
    captions = exercise.get('captions', [])
    if not (exercise.get('passage') or exercise.get('stimuli') or (isinstance(captions, list) and len(captions) >= 2)):
        return None
    # Reuse the lossless binding and untracked-workspace safety checks before
    # changing composition. This is an alternative layout, never a content edit.
    images = page.get('images')
    if not isinstance(images, list) or not 1 <= len(images) <= 4:
        return None
    base = (single_illustration_recovery(page, minimum_font, visual_area) if len(images) == 1
            else multiple_illustration_recovery(page, minimum_font, visual_area))
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
    if len(images) == 1:
        if page.get('_recovery_config',{}).get('stimulus_limit'):
            side=math.ceil(math.sqrt(visual_area*1.04))
            artwork=f'<img data-asset="{asset}" style="width:{side}mm;height:{side}mm"/>'
        else:
            artwork = f'<img data-asset="{asset}" style="width:100mm;height:{height}mm"/>' 
    else:
        from core.illustration_gallery import illustration_grid
        try:
            artwork = illustration_grid([image['id'] for image in base['images']], visual_area)
        except ValueError:
            return None
    text_style = f'font-size:{minimum_font}pt;line-height:1.2;margin:0 0 2mm'
    pieces = [f'<h1 data-content="title" style="font-size:{minimum_font+5}pt;color:{accent};'
              f'background-color:{wash};padding:3mm;margin:0 0 3mm"></h1>',
              f'<p data-content="name" style="{text_style}"></p>']
    if re.search(r'Date:\s*_+', base['html']):
        pieces.append(f'<p data-content="date" style="{text_style}"></p>')
    supporting = [f'<p data-content="directions" style="{text_style}"></p>']
    for slot in supporting_slot_ids(page,exercise):
        supporting.append(f'<p data-content="{slot}" style="{text_style}"></p>')
    pieces.append('<table style="width:175mm;table-layout:fixed;border-spacing:0;margin:0 0 3mm"><tbody><tr>'
                  f'<td style="width:100mm;padding:0;vertical-align:top">{artwork}</td>'
                  '<td style="width:75mm;padding:0 0 0 3mm;vertical-align:top">' + ''.join(supporting) +
                  '</td></tr></tbody></table>')
    for question in exercise.get('questions', []):
        pieces.append(f'<div data-content="question_{question["id"]}" style="{text_style};'
                      f'padding:1mm;border-top:0.5mm solid {accent}"></div>')
    result = deepcopy(base)
    result['html'] = ''.join(pieces)
    return result


def retained_table_artwork_recovery(page: dict, minimum_font: int, visual_area: float) -> dict | None:
    """Move one illustration out of a narrow column while retaining all data-table cells.

    Only a one-row two-column image/text layout table may be unwrapped. Tables
    with headers or multiple data rows retain their structure. No text, questions,
    sources or independently authored response panels are removed.
    """
    if (page.get('exercise',{}).get('render_mode')!='authored'
            or not isinstance(page.get('images'),list) or len(page['images'])!=1
            or '<table' not in page.get('html','').lower()
            or not 0<visual_area<=22000): return None
    checked=deepcopy(page)
    try:
        compile_exercise(checked,recovery_profile(page,minimum_font),page.get('_recovery_title','Internal layout check'))
        parser=CanonicalTextContainers({});parser.feed(page['html']);parser.close()
        if parser.stack: return None
        asset=page['images'][0]['id'];targets=[]

        def find(node):
            """Locate the sole declared illustration without interpreting its pixels."""
            if isinstance(node,str) or 'comment' in node: return
            if node['tag']=='img' and dict(node['attrs']).get('data-asset')==asset: targets.append(node)
            for child in node['children']: find(child)

        for node in parser.root: find(node)
        if len(targets)!=1: return None
        target=targets[0]

        def image_only(node):
            """Prove a wrapper holds only the image, not labels or blank writing panels."""
            if isinstance(node,str): return not node.strip()
            if node is target: return True
            if 'comment' in node or node['tag'] not in {'div','section','p','span','td'}: return False
            if any(k=='data-content' for k,_ in node['attrs']): return False
            return bool(node['children']) and any(not isinstance(c,str) for c in node['children']) and all(image_only(c) for c in node['children'])

        def strip_sizes(node, names):
            """Remove column/frame clamps from a proven layout wrapper only."""
            node['attrs']=[(k,';'.join(d for d in (v or '').split(';')
                if d.split(':',1)[0].strip().lower() not in names) if k=='style' else v) for k,v in node['attrs']]

        def extract(node):
            """Extract art and unwrap only a verified image/text layout table."""
            if isinstance(node,str) or 'comment' in node: return node
            if node is target: return None
            if image_only(node) and node['tag'] in {'div','section','p','span'}: return None
            if node['tag']=='table':
                rows=[]

                def rows_of(item):
                    """Read direct layout rows without entering nested data tables."""
                    if isinstance(item,str): return not item.strip()
                    if 'comment' in item: return False
                    if item['tag']=='tr': rows.append(item);return True
                    if item['tag'] in {'tbody','thead','tfoot'}: return all(rows_of(c) for c in item['children'])
                    return False

                valid=all(rows_of(c) for c in node['children'])
                cells=[c for c in rows[0]['children'] if not isinstance(c,str) or c.strip()] if valid and len(rows)==1 else []
                if (len(cells)==2 and all(isinstance(c,dict) and c.get('tag')=='td' for c in cells)
                        and not any(k in {'colspan','rowspan'} for c in cells for k,_ in c['attrs'])):
                    flags=[image_only(c) for c in cells]
                    if sum(flags)==1:
                        other=deepcopy(cells[1 if flags[0] else 0]);other['tag']='div'
                        strip_sizes(other,{'width','min-width','max-width','height','min-height','max-height'})
                        other['children']=[n for c in other['children'] if (n:=extract(c)) is not None]
                        return other
            was_image=image_only(node)
            node['children']=[n for c in node['children'] if (n:=extract(c)) is not None]
            if was_image and node['tag']=='td': strip_sizes(node,{'height','min-height','max-height'})
            return node

        from core.print_grid import literal_html
        roots=[n for node in parser.root if (n:=extract(node)) is not None]
        side=math.ceil(math.sqrt(visual_area)*1.025)
        if side>155: return None
        image=deepcopy(target)
        strip_sizes(image,{'width','height','min-width','max-width','min-height','max-height','object-fit'})
        attrs=dict(image['attrs']);attrs['style']=attrs.get('style','')+f';width:{side}mm;height:{side}mm;object-fit:contain'
        image['attrs']=list(attrs.items())
        art={'tag':'div','attrs':[('style','text-align:center;margin:0 0 3mm')],'children':[image]}
        # Keep the planned heading first, then give the shared illustration full width.
        index=next((i+1 for i,n in enumerate(roots) if isinstance(n,dict) and dict(n.get('attrs',[])).get('data-content')=='title'),0)
        roots.insert(index,art)
        result=deepcopy(page);result['html']=''.join(literal_html(n) for n in roots)
        return result
    except (ValueError,TypeError,KeyError,IndexError): return None


def layout_recovery_candidates(page: dict, minimum_font: int, visual_area: float):
    """Try bounded lossless compositions with sufficient art before another model rewrite."""
    resized=readable_exact_layout(page,minimum_font,visual_area)
    if resized is not None:
        yield resized
    table_art=retained_table_artwork_recovery(page,minimum_font,visual_area)
    if table_art is not None:
        yield table_art
    if page.get('_recovery_config',{}).get('stimulus_limit'):
        mixed_reading=reading_panel_recovery(page,minimum_font,visual_area)
        if mixed_reading is not None:
            yield mixed_reading
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
        compact_exact = exact_caption_grid_recovery(page,minimum_font,visual_area)
        if compact_exact is not None:
            yield compact_exact

