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
    """Save the exact previewed high-resolution work material, with no model-generated marks."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'blank-{asset_id}-{kind}.png'
    path.write_bytes(template_png(kind))
    return path


def template_png(kind: str) -> bytes:
    """Return cached, deterministic PNG bytes for preview and final delivery."""
    return _template_png(kind)


from functools import lru_cache
import io
import math


@lru_cache(maxsize=32)
def _template_png(kind: str) -> bytes:
    """Draw work surfaces locally; every unfinished right half stays free of example motifs."""
    from core.work_templates import SUBJECTS
    if kind.endswith('_reference') and kind[:-10] in SUBJECTS:
        from PIL import ImageOps
        original=Image.open(io.BytesIO(_template_png(kind[:-10]+'_symmetry'))).convert('RGB')
        original.paste(ImageOps.mirror(original.crop((0,0,900,1320))),(900,0))
        output=io.BytesIO();original.save(output,format='PNG',dpi=(300,300));return output.getvalue()
    symmetry=kind.endswith('_symmetry') and kind[:-9] in SUBJECTS
    if not symmetry and kind not in {'blanket','pumpkin_face','pattern_grid','banner_plan','banner_symmetry'}:
        raise ValueError('Unsupported blank template')
    size=(1800,1320) if symmetry else (1800,1020) if kind in {'banner_plan','banner_symmetry'} else (1800,1000)
    image=Image.new('RGB',size,'white');draw=ImageDraw.Draw(image);ink='#344454'
    if symmetry:
        subject=kind[:-9]
        if subject=='skull':
            points=[]
            def curve(a,b,c,d):
                """Sample a cubic outline at print resolution without an SVG dependency."""
                for i in range(61):
                    t=i/60;u=1-t
                    points.append((u**3*a[0]+3*u*u*t*b[0]+3*u*t*t*c[0]+t**3*d[0],
                                   u**3*a[1]+3*u*u*t*b[1]+3*u*t*t*c[1]+t**3*d[1]))
            curve((900,75),(1450,-10),(1750,450),(1540,780))
            points.extend([(1390,900),(1390,1110)])
            curve((1390,1110),(1390,1260),(1390,1260),(1240,1260))
            points.append((560,1260))
            curve((560,1260),(410,1260),(410,1260),(410,1110))
            points.extend([(410,900),(260,780)])
            curve((260,780),(50,450),(350,-10),(900,75))
            draw.polygon(points,fill='white');draw.line(points+[points[0]],fill=ink,width=9,joint='curve')
            for box in ((440,440,720,700),(1080,440,1360,700)):
                draw.ellipse(box,outline=ink,width=8)
            draw.polygon([(900,715),(830,835),(970,835)],outline=ink,width=8)
            draw.rounded_rectangle((615,945,1185,1100),radius=35,outline=ink,width=8)
            for x in (710,805,900,995,1090):draw.line((x,950,x,1095),fill=ink,width=6)
        elif subject=='butterfly':
            for box in ((160,90,920,780),(880,90,1640,780),(240,620,920,1240),(880,620,1560,1240)):
                draw.ellipse(box,outline=ink,width=9)
            draw.rounded_rectangle((855,300,945,1200),radius=40,outline=ink,width=8)
            draw.line((875,310,780,150),fill=ink,width=7);draw.line((925,310,1020,150),fill=ink,width=7)
        elif subject=='leaf':
            points=[]
            for i in range(181):
                y=65+i*6.5;half=620*math.sin(math.pi*i/180)
                points.append((900-half,y))
            points += [(1800-x,y) for x,y in reversed(points)]
            draw.line(points+[points[0]],fill=ink,width=9,joint='curve')
        elif subject=='heart':
            points=[]
            for a,b,c,d in (
                    ((900,1240),(650,1070),(150,700),(180,390)),
                    ((180,390),(180,50),(600,0),(900,300)),
                    ((900,300),(1200,0),(1620,50),(1620,390)),
                    ((1620,390),(1650,700),(1150,1070),(900,1240))):
                for i in range(61):
                    t=i/60;u=1-t
                    points.append((u**3*a[0]+3*u*u*t*b[0]+3*u*t*t*c[0]+t**3*d[0],
                                   u**3*a[1]+3*u*u*t*b[1]+3*u*t*t*c[1]+t**3*d[1]))
            draw.line(points+[points[0]],fill=ink,width=9,joint='curve')
        else:
            draw.rounded_rectangle((840,70,960,295),radius=20,outline=ink,width=8)
            draw.ellipse((180,240,1620,1230),outline=ink,width=9)
        # Supply reference motifs on the LEFT only, clipped at the symmetry
        # axis. Base outlines are symmetrical; the right decorative half is blank.
        layer=Image.new('RGB',image.size,'white');motifs=ImageDraw.Draw(layer)
        for cx,cy in ((650,430 if subject in {'leaf','pumpkin'} else 270),(550,820)):
            for i in range(8):
                angle=2*math.pi*i/8;x=cx+70*math.cos(angle);y=cy+70*math.sin(angle)
                motifs.ellipse((x-31,y-31,x+31,y+31),outline=ink,width=7)
            motifs.ellipse((cx-25,cy-25,cx+25,cy+25),outline=ink,width=7)
        motifs.line((550,360,620,390,550,420,620,450),fill=ink,width=8)
        # Transparent-style composition retains every anatomical outline.
        mask=layer.convert('L').point(lambda p:255 if p<250 else 0)
        mask.paste(0,(900,0,1800,1320))
        if subject in {'skull','leaf','heart'}:
            from PIL import ImageChops
            silhouette=Image.new('L',image.size,0);ImageDraw.Draw(silhouette).polygon(points,fill=255)
            mask=ImageChops.multiply(mask,silhouette)
        image.paste(layer,(0,0),mask)
        draw=ImageDraw.Draw(image)
        for y in range(35,1290,30):draw.line((900,y,900,y+15),fill='#9AA8B2',width=3)
    elif kind in {'banner_plan','banner_symmetry'}:
        draw.rectangle((120,120,1680,900),outline=ink,width=8)
        if kind=='banner_symmetry':
            # Reference motifs belong to the left half only. Diamonds and a
            # marigold provide exact repeatable shapes, never AI counting data.
            for cx,cy in ((430,340),(600,700)):
                for i in range(8):
                    angle=2*math.pi*i/8;x=cx+65*math.cos(angle);y=cy+65*math.sin(angle)
                    draw.ellipse((x-26,y-26,x+26,y+26),outline=ink,width=6)
                draw.ellipse((cx-20,cy-20,cx+20,cy+20),outline=ink,width=6)
            for cx,cy in ((690,340),(350,680)):
                draw.polygon([(cx,cy-65),(cx+45,cy),(cx,cy+65),(cx-45,cy)],outline=ink,width=7)
        for y in range(140,880,36):draw.line((900,y,900,y+18),fill='#9AA8B2',width=3)
    elif kind=='pumpkin_face':
        draw.rounded_rectangle((855,65,945,230),radius=20,outline=ink,width=7)
        for box in ((290,180,1130,925),(670,180,1510,925),(520,180,1280,925)):
            draw.ellipse(box,outline=ink,width=7)
    else:
        draw.rectangle((140,100,1660,900),outline=ink,width=7)
        if kind=='pattern_grid':
            for x in range(330,1660,190):draw.line((x,100,x,900),fill=ink,width=4)
            for y in range(300,900,200):draw.line((140,y,1660,y),fill=ink,width=4)
        else:
            for x in range(160,1660,40):
                draw.line((x,100,x,55),fill=ink,width=4);draw.line((x,900,x,945),fill=ink,width=4)
    output=io.BytesIO();image.save(output,format='PNG',dpi=(300,300))
    return output.getvalue()
