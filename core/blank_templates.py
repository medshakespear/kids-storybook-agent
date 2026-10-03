"""Draw usable blank student templates locally without image-model completion marks."""
from pathlib import Path
from PIL import Image, ImageDraw


def template_kind(exercise: dict) -> str | None:
    """Recognize explicitly requested blank materials, not ordinary decorative images."""
    import re
    text = ' '.join([str(exercise.get('directions', ''))] +
                    [str(q.get('prompt', '')) for q in exercise.get('questions', []) if isinstance(q, dict)]).lower()
    if not re.search(r'\b(?:blank|faceless)\b', text):
        return None
    if 'blanket' in text:
        return 'blanket'
    if 'pumpkin' in text and ('face' in text or 'faceless' in text):
        return 'pumpkin_face'
    if re.search(r'blank\s+(?:pattern\s+)?(?:grid|template)', text):
        return 'pattern_grid'
    return None


def draw_blank_template(kind: str, folder, asset_id: str) -> Path:
    """Save a high-resolution white template with outlines and no completed answers."""
    if kind not in {'blanket', 'pumpkin_face', 'pattern_grid'}:
        raise ValueError('Unsupported blank template')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'blank-{asset_id}-{kind}.png'
    image = Image.new('RGB', (1800, 1000), 'white')
    draw = ImageDraw.Draw(image)
    ink = '#344454'
    if kind == 'pumpkin_face':
        draw.rounded_rectangle((855, 65, 945, 230), radius=20, outline=ink, width=7)
        for box in [(290, 180, 1130, 925), (670, 180, 1510, 925), (520, 180, 1280, 925)]:
            draw.ellipse(box, outline=ink, width=7)
    else:
        draw.rectangle((140, 100, 1660, 900), outline=ink, width=7)
        if kind == 'pattern_grid':
            for x in range(330, 1660, 190):
                draw.line((x, 100, x, 900), fill=ink, width=4)
            for y in range(300, 900, 200):
                draw.line((140, y, 1660, y), fill=ink, width=4)
        else:
            # Leave the blanket surface completely blank for students' own designs.
            for x in range(160, 1660, 40):
                draw.line((x, 100, x, 55), fill=ink, width=4)
                draw.line((x, 900, x, 945), fill=ink, width=4)
    image.save(path, dpi=(300, 300))
    return path
