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
