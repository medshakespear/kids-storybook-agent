"""Assemble generated story text and illustrations into a printable A4 PDF."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from weasyprint import HTML


FONT_SIZES = {
    "Pre-K-K": "25pt",
    "1st-2nd": "21pt",
    "3rd-4th": "17pt",
    "5th-6th": "14pt",
}


def _layout_class(style: str) -> str:
    """Translate a configured placement style into a supported CSS class."""

    supported = {"bottom_band", "top_band", "side_panel", "balanced_panel"}
    return style if style in supported else "bottom_band"


def build_pdf(
    story: dict[str, Any],
    image_paths: list[str | Path],
    grade_band_config: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Build an A4 portrait PDF with a title page and one page per scene."""

    if len(image_paths) != len(story["pages"]):
        raise ValueError("The image count must match the number of story pages.")

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    grade_band = story["grade_band"]
    font_size = FONT_SIZES.get(grade_band, "16pt")
    placement = _layout_class(grade_band_config["text_placement_style"])

    pages_html: list[str] = []
    for page, image_path in zip(story["pages"], image_paths, strict=True):
        image_uri = Path(image_path).resolve().as_uri()
        story_text = html.escape(page["text"])
        pages_html.append(
            f"""
            <section class="story-page {placement}">
              <img class="illustration" src="{image_uri}" alt="" />
              <div class="text-band"><p>{story_text}</p></div>
              <span class="page-number">{int(page['page_number'])}</span>
            </section>
            """
        )

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4 portrait; margin: 0; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; font-family: "DejaVu Sans", Arial, sans-serif; }}
  section {{ width: 210mm; height: 297mm; page-break-after: always; position: relative; overflow: hidden; }}
  section:last-child {{ page-break-after: auto; }}
  .title-page {{
    display: flex; flex-direction: column; justify-content: center; align-items: center;
    padding: 24mm; text-align: center; color: #18324a;
    background: linear-gradient(145deg, #fff4c7, #d9f4ee 48%, #dce8ff);
  }}
  .title-page::before, .title-page::after {{
    content: ""; position: absolute; border-radius: 50%; opacity: .28;
    background: #ff9f8f;
  }}
  .title-page::before {{ width: 105mm; height: 105mm; left: -35mm; top: -30mm; }}
  .title-page::after {{ width: 85mm; height: 85mm; right: -20mm; bottom: -20mm; background: #729fe8; }}
  h1 {{ font-size: 34pt; line-height: 1.12; margin: 0 0 14mm; max-width: 165mm; z-index: 1; }}
  .subtitle {{ font-size: 17pt; line-height: 1.5; z-index: 1; }}
  .grade {{ display: inline-block; margin-top: 10mm; padding: 3mm 7mm; border-radius: 20mm; background: rgba(255,255,255,.7); }}
  .illustration {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
  .text-band {{
    position: absolute; z-index: 2; background: rgba(255,255,255,.94); color: #17212b;
    box-shadow: 0 0 7mm rgba(0,0,0,.14); padding: 8mm 12mm;
  }}
  .text-band p {{ margin: 0; font-size: {font_size}; line-height: 1.42; }}
  .bottom_band .text-band {{ left: 0; right: 0; bottom: 0; min-height: 61mm; display: flex; align-items: center; }}
  .top_band .text-band {{ left: 0; right: 0; top: 0; min-height: 55mm; display: flex; align-items: center; }}
  .side_panel .text-band {{ right: 0; top: 0; bottom: 0; width: 39%; display: flex; align-items: center; padding: 14mm 10mm; }}
  .balanced_panel .text-band {{ left: 8mm; right: 8mm; bottom: 8mm; min-height: 76mm; border-radius: 5mm; display: flex; align-items: center; }}
  .page-number {{
    position: absolute; z-index: 3; right: 5mm; bottom: 3mm; min-width: 8mm; height: 8mm;
    border-radius: 4mm; background: rgba(255,255,255,.85); color: #34495e; font-size: 9pt;
    line-height: 8mm; text-align: center;
  }}
  .top_band .page-number {{ top: 3mm; bottom: auto; }}
</style>
</head>
<body>
  <section class="title-page">
    <h1>{html.escape(story['title'])}</h1>
    <div class="subtitle">An original illustrated story<br>
      <span class="grade">For grades {html.escape(grade_band)}</span>
    </div>
  </section>
  {''.join(pages_html)}
</body>
</html>"""

    HTML(string=document, base_url=str(target.parent.resolve())).write_pdf(str(target))
    if not target.exists() or target.stat().st_size < 1024:
        raise RuntimeError("WeasyPrint did not produce a valid PDF file.")
    return target

