"""Normalize printable image geometry without changing assets, text or response spaces."""
import html
import math
import re
from html.parser import HTMLParser

import tinycss2


class ImageAttributes(HTMLParser):
    """Read one image's attributes using HTML parsing rather than CSS substring guesses."""

    def handle_starttag(self, tag, attrs):
        """Retain attributes for a single image tag."""
        self.attrs = attrs


def length_mm(value: str) -> float | None:
    """Convert explicit physical dimensions to millimetres; never resolve parent-relative height."""
    match = re.fullmatch(r'(\d+(?:\.\d+)?|\.\d+)\s*(mm|cm|in|pt|px)',value.strip(),re.I)
    if not match:
        return None
    return float(match[1])*{'mm':1,'cm':10,'in':25.4,'pt':25.4/72,'px':25.4/96}[match[2].lower()]


def normalize_image_dimensions(markup: str, visuals: dict, area: float, clean) -> str:
    """Supply missing/auto dimensions, convert units, and leave all print checks mandatory."""
    def replace(match):
        """Normalize only this img's own width/height declarations and retain every other attribute."""
        parser=ImageAttributes();parser.feed(match[0]);parser.close()
        attrs=getattr(parser,'attrs',[]);data=dict(attrs)
        if len(attrs)!=len(data):
            raise ValueError('Image attributes must not repeat')
        style=clean(data.get('style',''))
        declarations=tinycss2.parse_declaration_list(style,skip_comments=True,skip_whitespace=True)
        sizes={d.lower_name:tinycss2.serialize(d.value).strip() for d in declarations if d.lower_name in {'width','height'}}
        width=sizes.get('width','auto');height=sizes.get('height','auto')
        w=length_mm(width);h=length_mm(height)
        if (w is not None and w<=0) or (h is not None and h<=0) or width=='0' or height=='0':
            raise ValueError('Image width and height must be positive; zero dimensions hide artwork')
        percent=re.fullmatch(r'(\d+(?:\.\d+)?|\.\d+)%',width)
        if percent and float(percent[1])<=0:
            raise ValueError('Image width must be positive')
        if w is None and not percent and width.lower()!='auto':
            raise ValueError('Image width must use physical units, percent or auto')
        if re.fullmatch(r'0+(?:\.0+)?%',height):
            raise ValueError('Image height must be positive')
        if h is None and height.lower()!='auto' and not re.fullmatch(r'(\d+(?:\.\d+)?|\.\d+)%',height):
            raise ValueError('Image height must use physical units or auto')
        canonical_height = re.fullmatch(r'(\d+(?:\.\d+)?|\.\d+)mm',height)
        canonical_width = re.fullmatch(r'(\d+(?:\.\d+)?|\.\d+)(mm|%)',width)
        if canonical_height and canonical_width and (not data.get('data-visual') or width.endswith('mm')):
            return match[0]  # Keep already valid geometry and markup byte-for-byte.
        display_width=w if w is not None else 175*float(percent[1])/100 if percent else 175
        output_width=f'{w:g}mm' if w is not None else (f'{display_width:g}mm' if data.get('data-visual') else width) if percent else '175mm'
        if h is None:
            vid=data.get('data-visual')
            if vid in visuals:
                svg=visuals[vid][0]
                native_w=re.search(r'<svg[^>]*\bwidth="([0-9.]+)"',svg)
                native_h=re.search(r'<svg[^>]*\bheight="([0-9.]+)"',svg)
                if not native_w or not native_h:
                    raise ValueError('Exact image needs validated intrinsic dimensions')
                h=display_width*float(native_h[1])/float(native_w[1])
            else:
                h=max(45,min(100,math.ceil(area/max(display_width,1))))
        kept=[d for d in declarations if d.lower_name not in {'width','height'}]
        data['style']=tinycss2.serialize(kept)+f';width:{output_width};height:{h:g}mm'
        return '<img '+' '.join(f'{k}="{html.escape(v or "",quote=True)}"' for k,v in data.items())+'/>'
    return re.sub(r'<img\b(?:[^\'\">]|\'[^\']*\'|"[^"]*")*>',replace,markup,flags=re.I)
