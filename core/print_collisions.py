"""Detect overlapping printed text and images using actual rendered leaf boxes."""


def check_print_collisions(document) -> None:
    """Reject meaningful text collisions while ignoring nested layout containers."""
    for number, page in enumerate(document.pages, 1):
        leaves = []
        def visible_boxes(box):
            """Exclude the deliberately cropped store logo from leaf collision checks."""
            element = getattr(box, 'element', None)
            if element is not None and 'store-logo' in element.get('class', '').split():
                return
            yield box
            for child in box.all_children():
                yield from visible_boxes(child)
        for box in visible_boxes(page._page_box):
            text = getattr(box, 'text', '')
            image = box.element_tag == 'img' and hasattr(box, 'replacement')
            if not (text.strip() or image):
                continue
            leaves.append((box.position_x, box.position_y, box.width, box.height,
                           'image' if image else text[:65], image))
        for i, a in enumerate(leaves):
            for b in leaves[i + 1:]:
                if a[5] and b[5]:
                    continue
                width = min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0])
                height = min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1])
                # Small font-metric intersections are not visible collisions.
                if width > 2 and height > 2:
                    raise ValueError(f'Design overlap: page {number}: {a[4]!r} overlaps {b[4]!r}. '
                                     'Use normal vertical flow and auto-height text containers; '
                                     'retain all content and readable fonts.')
