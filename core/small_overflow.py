"""Recover a small vertical spill by resizing illustrative art, never student text/workspace."""
import re


def recover_small_overflow(markup: str, document, profile: dict) -> str | None:
    """Offer one measured candidate for a <=8mm spill while preserving visual-area floors."""
    if not profile.get('visual_area_mm2') or len(document.pages) != 1:
        return None
    boxes = [b for b in document.pages[0]._page_box.descendants()
             if b.element_tag not in {None, 'html', 'body', 'article'}]
    if not boxes:
        return None
    if max(b.border_box_x()+b.border_width() for b in boxes) > 198*96/25.4+1:
        return None
    excess = (max(b.border_box_y()+b.border_height() for b in boxes)-283*96/25.4)*25.4/96
    if not 0 < excess <= 8:
        return None
    images = []
    for match in re.finditer(r'<img\b[^>]*>', markup, re.I):
        width = re.search(r'(?<!-)\bwidth\s*:\s*([0-9.]+)mm', match[0], re.I)
        height = re.search(r'(?<!-)\bheight\s*:\s*([0-9.]+)mm', match[0], re.I)
        if width and height:
            images.append((match, float(width[1]), float(height[1])))
    candidates = [v for v in images if re.search(r'\bdata-asset\s*=', v[0][0], re.I)]
    if not candidates:
        return None  # Exact SVG labels and student response panels cannot be shrunk.
    match, width, height = max(candidates, key=lambda v: v[1]*v[2])
    new_height = height-excess-2
    if new_height < 35:
        return None
    areas = [w*(new_height if m.start()==match.start() else h) for m,w,h in images]
    floor = profile['visual_area_mm2']
    from core.visual_area import sufficient_visual_area
    if not sufficient_visual_area(areas, floor):
        return None
    tag = re.sub(r'(?<!-)\bheight\s*:\s*[0-9.]+mm', f'height:{new_height:.2f}mm',match[0],flags=re.I)
    return markup[:match.start()]+tag+markup[match.end():]
