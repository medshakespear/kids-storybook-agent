"""Colorful, grade-scaled classroom worksheets with code-drawn instructional art."""
from __future__ import annotations

import base64
import html
from pathlib import Path
from weasyprint import HTML


def esc(value: object) -> str:
    """Escape every model-generated string before placing it in HTML."""
    return html.escape(str(value), quote=True)


def icon_svg(kind: str, color: str = "#007F82") -> str:
    """Draw reliable countable geometry; no AI-rendered letters or quantities."""
    shapes = {
        "circle": '<circle cx="24" cy="24" r="17"/>',
        "square": '<rect x="8" y="8" width="32" height="32" rx="4"/>',
        "triangle": '<path d="M24 6 L43 40 H5 Z"/>',
        "star": '<path d="M24 3 L30 17 L45 18 L34 28 L37 44 L24 36 L11 44 L14 28 L3 18 L18 17 Z"/>',
        "heart": '<path d="M24 42 C-8 23 5 -3 24 13 C43 -3 56 23 24 42 Z"/>',
        "leaf": '<path d="M8 40 Q0 5 41 6 Q45 40 8 40 Z"/><path d="M9 39 L34 13" fill="none" stroke="white" stroke-width="2"/>',
        "book": '<path d="M4 8 Q14 4 24 10 Q34 4 44 8 V40 Q34 36 24 42 Q14 36 4 40 Z"/><path d="M24 10 V40" stroke="white" stroke-width="2"/>',
    }
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="{color}" stroke="#244451" stroke-width="1.3">{shapes[kind]}</svg>'


def svg_image(svg: str, css_class: str = "symbol") -> str:
    """Embed trusted code-authored SVG as an image for consistent PDF rendering."""
    data = base64.b64encode(svg.encode()).decode()
    return f'<img class="{css_class}" src="data:image/svg+xml;base64,{data}" alt=""/>'


def lines(count: int = 2) -> str:
    """Provide actual writing room, not underscores squeezed into prose."""
    return '<div class="writing-line"></div>' * count


def _trace_svg(word: str) -> str:
    """Render outlined uppercase practice letters with a dashed stroke and guide."""
    font_size = min(62, 570 / (len(word) * 1.1))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 90">'
            '<path d="M0 75 H600 M0 20 H600" stroke="#adbac1" stroke-width="1"/>'
            '<path d="M0 47 H600" stroke="#ccd4d8" stroke-dasharray="6 5"/>'
            f'<text x="8" y="73" font-family="DejaVu Sans" font-size="{font_size:.1f}" font-weight="bold" '
            f'fill="none" stroke="#4b6272" stroke-width="1" stroke-dasharray="2 3">{esc(word)}</text></svg>')


def _student_content(page: dict, config: dict) -> str:
    """Render complete task data with answers absent from the student page."""
    kind, items = page["type"], page["items"]
    color = config["accent"]
    if kind == "count":
        rows = []
        for i, item in enumerate(items, 1):
            shapes = ''.join(svg_image(icon_svg(item["icon"], color if j % 2 == 0 else config["secondary"])) for j in range(item["count"]))
            rows.append(f'<div class="count-row"><b>{i}.</b><div class="objects">{shapes}</div><div class="answer-box"></div></div>')
        return '<p class="action">Count each group. Write the total in the box.</p>' + ''.join(rows)
    if kind == "arithmetic":
        symbols = {"+": "+", "-": "−", "*": "×", "/": "÷"}
        return '<p class="action">Solve each calculation. Show your thinking below it.</p>' + ''.join(
            f'<div class="math-row"><span class="item-no">{i}.</span><b>{v["a"]} {symbols[v["op"]]} {v["b"]} = </b><span class="answer-box"></span>{lines(1)}</div>'
            for i, v in enumerate(items, 1))
    if kind == "matching":
        # Reverse/rotate deterministically so the pairs are not aligned in answer order.
        order = list(range(1, len(items))) + [0]
        rows = ''.join(f'<tr><td class="match-card">{i+1}. {esc(items[i]["left"])}</td><td class="connector"></td>'
                       f'<td class="match-card">{chr(65+i)}. {esc(items[j]["right"])}</td></tr>' for i, j in enumerate(order))
        return '<p class="action">Draw a line to connect each matching pair.</p><table class="matching">' + rows + '</table>'
    if kind == "sort":
        categories = ''.join(f'<td class="sort-bin"><strong>{esc(c)}</strong><div class="bin-space"></div></td>' for c in page["categories"])
        cards = ''.join(f'<td class="cut-card">{esc(item["label"])}</td>' for item in items)
        return ('<p class="action">Cut out the cards. Place each card in its group. An adult can help with cutting.</p>'
                f'<table class="bins"><tr>{categories}</tr></table><p class="mini">CUT-OUT CARDS</p><table class="cards"><tr>{cards}</tr></table>')
    if kind == "reading":
        return f'<div class="passage">{esc(page["passage"])}</div>' + ''.join(
            f'<div class="question"><b>{i}. {esc(item["question"])}</b>{lines(2)}</div>' for i, item in enumerate(items, 1))
    if kind == "trace":
        return '<p class="action">Trace the outlined word. Then write it yourself on the next line.</p>' + ''.join(
            f'<div class="trace-row">{svg_image(_trace_svg(item["word"]), "trace-art")}{lines(1)}</div>' for item in items)
    if kind == "draw":
        criteria = ''.join(f'<li>{esc(c)}</li>' for c in page["criteria"])
        return (f'<div class="challenge">{esc(page["challenge"])}</div><ul class="criteria">{criteria}</ul>'
                '<div class="drawing-frame"><span>MY DESIGN / DRAWING</span></div>'
                + ('<p class="mini">Explain your idea, or tell an adult.</p>' if config['color_level'] >= 2 else '<p class="mini">Explain your design choices using the criteria.</p>') + lines(3))
    raise ValueError(f"Unsupported activity type: {kind}")


def _sheet(body: str, footer: str, css_class: str = "") -> str:
    """Wrap a single worksheet with a consistent footer and print margins."""
    return f'<section class="sheet {css_class}">{body}<footer>{esc(footer)}</footer></section>'


def build_activity_html(pack: dict, config: dict) -> str:
    """Compose a cover, teacher plan, student pages and separate teaching keys."""
    total = len(pack["pages"])
    level = config["color_level"]
    accent, wash = config["accent"], config["wash"]
    decorations = ''.join(svg_image(icon_svg(k, accent if i % 2 == 0 else config["secondary"]), "cover-symbol")
                          for i, k in enumerate(["book", "star", "leaf", "triangle"][:max(1, level + 1)]))
    cover = (f'<p class="eyebrow">THE CLASSROOM ACTIVITY COLLECTION</p><div class="cover-icons">{decorations}</div>'
             f'<h1>{esc(pack["title"])}</h1><p class="grade-pill">{esc(pack["grade_band"])} · PRINT &amp; PRACTICE</p>'
             f'<p class="overview">{esc(pack["overview"])}</p><div class="cover-summary">'
             f'<strong>{total} student activities</strong><br>Teacher plan · Answer keys · Support and stretch ideas</div>'
             '<p class="cover-note">Read. Think. Make. Explain.</p>')
    sheets = [_sheet(cover, "Original classroom exercises | A4 portrait", "cover")]
    objectives = ''.join(f'<li>{esc(v)}</li>' for v in pack["objectives"])
    plan = ''.join(f'<tr><td>{p["page_number"]}</td><td><strong>{esc(p["title"])}</strong></td><td>{p["minutes"]} min</td></tr>' for p in pack["pages"])
    teacher = (f'<p class="eyebrow">TEACHER COPY</p><h2>Your teaching plan</h2><h3>Learning goals</h3><ul>{objectives}</ul>'
               f'<h3>Materials</h3><p>{esc(", ".join(pack["materials"]))}</p>'
               '<p>Choose individual pages or use them as a sequence. Read directions aloud as needed. '
               'Keep the answer-key pages for the teacher. Print at actual size (100%).</p>'
               f'<table class="plan"><thead><tr><th>Task</th><th>Focus</th><th>Time</th></tr></thead><tbody>{plan}</tbody></table>'
               '<p class="review-note">Before classroom use or sale: review factual accuracy, reading level, cultural context, '
               'and answer keys. Open-ended responses may vary. These are static printable pages, not editable forms.</p>')
    sheets.append(_sheet(teacher, "Teacher plan | " + pack["grade_band"], "teacher"))
    for page in pack["pages"]:
        body = (f'<div class="topline"><span>ACTIVITY {page["page_number"]:02d}</span><span>{esc(pack["grade_band"])}</span></div>'
                f'<h2>{esc(page["title"])}</h2><div class="name-line">Name: ____________________ &nbsp; Date: __________</div>'
                f'<div class="directions">{esc(page["instructions"])}</div>' + _student_content(page, config))
        sheets.append(_sheet(body, f"Student page {page['page_number']} of {total} | {pack['title']}", f'student {page["type"]}'))
    for page in pack["pages"]:
        if page["type"] == "matching":
            n = len(page["items"])
            answers = [f"{i+1} -> {chr(65 + (i - 1) % n)}: {a}" for i, a in enumerate(page["answers"])]
        else:
            answers = page["answers"]
        answer_list = ''.join(f'<li>{esc(answer)}</li>' for answer in answers)
        body = (f'<p class="eyebrow">TEACHER COPY · KEY {page["page_number"]:02d}</p><h2>{esc(page["title"])}</h2>'
                f'<p><strong>Goal:</strong> {esc(page["objective"])}</p><h3>Answers / sample responses</h3><ol class="answers">{answer_list}</ol>'
                f'<h3>Teaching tip</h3><p>{esc(page["teacher_tip"])}</p>'
                f'<div class="teacher-panel"><h3>Support</h3><p>{esc(page["support"])}</p>'
                f'<h3>Stretch</h3><p>{esc(page["extension"])}</p></div>'
                '<h3>Quick observation</h3><p>What can the student do independently? What needs another model or example?</p>' + lines(4))
        sheets.append(_sheet(body, f"Answer key {page['page_number']} | Do not distribute with student worksheets", "teacher"))
    css = f"""
    @page {{size:A4; margin:14mm;}}
    * {{box-sizing:border-box;}} body {{margin:0;color:#233544;font-family:'DejaVu Sans',sans-serif;overflow-wrap:break-word;}}
    .sheet {{height:267mm;position:relative;break-after:page;padding-bottom:12mm;}}
    .sheet:last-child {{break-after:auto;}} h1 {{font-size:35pt;line-height:1.12;margin:12mm 0 8mm;}}
    h2 {{font-size:24pt;line-height:1.15;margin:5mm 0; color:{accent};}}
    h3 {{font-size:12pt;margin:5mm 0 2mm;color:{accent};}}
    p,li {{line-height:1.45;}} .student {{font-size:{config['student_font_pt']}pt;}}
    .teacher {{font-size:10pt;}} .teacher h2 {{font-size:24pt;}}
    .eyebrow,.mini {{font-size:9pt;font-weight:bold;letter-spacing:1px;color:{accent};}}
    .topline {{border-top:{2 + level}mm solid {accent};padding-top:3mm;display:flex;justify-content:space-between;font-size:9pt;font-weight:bold;}}
    .directions {{padding:4mm;background:{wash if level else '#ffffff'};border-left:1.4mm solid {accent};font-size:11pt;line-height:1.45;margin:5mm 0;}}
    .name-line {{font-size:10pt;margin:5mm 0;}} .action {{font-size:11pt;margin:3mm 0 5mm;}}
    footer {{position:absolute;bottom:0;left:0;right:0;border-top:.3mm solid #bacbd2;padding-top:3mm;font-size:8pt;color:#526775;}}
    .cover {{border-top:{3+level}mm solid {accent};padding:8mm;}}
    .cover-icons {{margin-top:14mm;}} .cover-symbol {{width:22mm;height:22mm;margin-right:6mm;}}
    .grade-pill {{display:inline-block;background:{wash};padding:3mm 5mm;border-radius:3mm;font-size:11pt;font-weight:bold;color:{accent};}}
    .overview {{font-size:14pt;line-height:1.6;}} .cover-summary {{background:{wash};padding:7mm;margin-top:12mm;font-size:13pt;line-height:1.8;}}
    .cover-note {{font-size:12pt;margin-top:14mm;color:{accent};}}
    table {{width:100%;border-collapse:separate;border-spacing:3mm;table-layout:fixed;}}
    .plan {{border-collapse:collapse;font-size:9pt;}} .plan td,.plan th {{padding:2.4mm;border-bottom:.3mm solid #dce4e7;text-align:left;}}
    .plan th:first-child,.plan td:first-child {{width:12mm;}} .plan th:last-child,.plan td:last-child {{width:20mm;}}
    .review-note {{font-size:8.5pt;background:{wash};padding:3mm;}}
    .symbol {{width:12mm;height:12mm;margin:1mm;}} .objects {{width:136mm;display:inline-block;vertical-align:middle;padding:3mm;}}
    .count-row {{border:.4mm solid #b8cdd3;border-radius:3mm;padding:2mm;margin:5mm 0;min-height:35mm;}}
    .count-row b {{font-size:12pt;}} .answer-box {{display:inline-block;border:.6mm solid {accent};width:19mm;height:18mm;vertical-align:middle;background:white;}}
    .count-row .answer-box {{width:17mm;}} .math-row {{padding:4mm 0;border-bottom:.4mm solid #d3dfe2;min-height:36mm;font-size:22pt;}}
    .item-no {{font-size:11pt;margin-right:5mm;}} .writing-line {{height:10mm;border-bottom:.3mm solid #8298a4;}}
    .match-card {{width:43%;border:.5mm solid {accent};background:{wash if level>1 else '#ffffff'};padding:6mm 4mm;height:33mm;font-size:13pt;}}
    .connector {{width:14%;}} .sort-bin {{border:.6mm solid {accent};vertical-align:top;text-align:center;padding:4mm;font-size:13pt;}}
    .bin-space {{height:66mm;}} .cut-card {{border:.4mm dashed #526775;padding:4mm;height:30mm;font-size:11pt;text-align:center;word-wrap:break-word;}}
    .passage {{padding:4mm;background:{wash};font-size:11pt;line-height:1.55;margin-bottom:5mm;}}
    .question {{font-size:10.5pt;margin-top:4mm;}} .question .writing-line {{height:8mm;}}
    .trace-art {{width:100%;height:22mm;}} .trace-row {{margin:4mm 0;}} .trace-row .writing-line {{height:11mm;}}
    .challenge {{padding:4mm;background:{wash};font-size:12pt;line-height:1.5;}} .criteria {{font-size:10.5pt;padding-left:6mm;}}
    .drawing-frame {{height:84mm;border:.5mm solid {accent};border-radius:3mm;margin:5mm 0;padding:3mm;}}
    .drawing-frame span {{font-size:8pt;color:#78909c;}} .answers li {{margin:4mm 0;font-size:11pt;}}
    .teacher-panel {{background:{wash};padding:2mm 5mm;margin-top:5mm;}}
    """
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><style>' + css + '</style></head><body>' + ''.join(sheets) + '</body></html>'


def build_activity_pdf(pack: dict, config: dict, output_path: str | Path) -> Path:
    """Render and reject unexpected pagination instead of silently clipping worksheets."""
    document = HTML(string=build_activity_html(pack, config)).render()
    expected = 2 + 2 * len(pack["pages"])
    if len(document.pages) != expected:
        raise ValueError(f"Worksheet pagination overflow: expected {expected}, got {len(document.pages)} pages")
    # Every non-footer text line must remain inside the usable worksheet area.
    for page in document.pages:
        for box in page._page_box.descendants():
            if type(box).__name__ == "LineBox" and box.element_tag != "footer":
                if box.position_y + box.height > (14 + 253) * 96 / 25.4:
                    raise ValueError("Worksheet content extends into the footer; shorten generated text")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.write_pdf(str(target))
    return target
