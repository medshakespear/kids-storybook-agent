"""Compact printable compositions for multiple declared exercise illustrations."""
import math
import re


def illustration_gallery(ids: list[str], height: float) -> str:
    """Place 2-4 substantial panels in one row without cropping or dropping any asset."""
    if not 2 <= len(ids) <= 4 or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,30}',aid) for aid in ids):
        raise ValueError('Gallery needs 2-4 declared lowercase illustration IDs')
    if not math.isfinite(height) or not 0 < height <= 150:
        raise ValueError('Gallery needs a positive printable height at most 150mm')
    # Leave a millimetre between panels; the area budget uses the actual image widths.
    width = (175-(len(ids)-1))/len(ids)
    cells = ''.join(f'<td style="width:{width+(1 if index<len(ids)-1 else 0):.4f}mm;padding:0 {1 if index<len(ids)-1 else 0}mm 0 0;vertical-align:middle">'
                    f'<img data-asset="{aid}" style="display:block;width:{width:.4f}mm;height:{height:.4f}mm"/></td>'
                    for index,aid in enumerate(ids))
    return ('<table style="width:175mm;table-layout:fixed;border-spacing:0;margin:0 0 3mm">'
            '<tbody><tr>'+cells+'</tr></tbody></table>')


def gallery_minimum_height(count: int, area: float) -> int:
    """Meet the total artwork floor with room for rounding and panel gutters."""
    return math.ceil(area*1.04/(175-(count-1)))


def illustration_grid(ids: list[str], area: float, width: float = 100) -> str:
    """Fit 2-4 equal substantial panels in a compact two-column artwork block."""
    if (not 2 <= len(ids) <= 4 or len(set(ids)) != len(ids)
            or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', aid) for aid in ids)):
        raise ValueError('Grid needs 2-4 distinct declared lowercase illustration IDs')
    if not math.isfinite(area) or area <= 0 or not math.isfinite(width) or not 60 <= width <= 175:
        raise ValueError('Grid needs a positive artwork budget and printable width')
    panel_width = (width - 1) / 2
    panel_height = math.ceil(area * 1.04 / (len(ids) * panel_width))
    rows = math.ceil(len(ids) / 2)
    if rows * panel_height + rows - 1 > 150:
        raise ValueError('Artwork grid cannot fit within its printable height budget')
    markup = []
    for row in range(rows):
        cells = []
        for col in range(2):
            index = row * 2 + col
            bottom = 1 if row < rows - 1 else 0
            right = 1 if col == 0 else 0
            image = (f'<img data-asset="{ids[index]}" style="display:block;width:{panel_width:.4f}mm;'
                     f'height:{panel_height}mm"/>' if index < len(ids) else '')
            cells.append(f'<td style="width:{panel_width+right:.4f}mm;padding:0 {right}mm {bottom}mm 0;'
                         f'vertical-align:top">{image}</td>')
        markup.append('<tr>' + ''.join(cells) + '</tr>')
    return (f'<table style="width:{width:g}mm;table-layout:fixed;border-spacing:0;margin:0">'
            '<tbody>' + ''.join(markup) + '</tbody></table>')
