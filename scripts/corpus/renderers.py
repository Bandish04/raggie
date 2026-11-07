# SPDX-License-Identifier: Apache-2.0

"""Format renderers for the sample corpus (deterministic output).

Every renderer writes the same plain text the golden set quotes; layout is kept
extraction-friendly (single-column PDFs, short table cells) because the workers
read PDFs with pdfplumber's layout mode, DOCX via python-docx (paragraphs, then
tables), XLSX as raw cell values and PPTX shape by shape.
"""

from __future__ import annotations

import datetime as dt
import io
import random
import re
import textwrap
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from model import Bullets, Doc, H, P, PageBreak, Table

COMPANY_TR = "Nebula Teknoloji A.Ş."
COMPANY_EN = "Nebula Teknoloji A.Ş."
COMPANY_CAPS = "NEBULA TEKNOLOJİ A.Ş."


def tr_upper(text: str) -> str:
    """Turkish-aware upper case (i -> İ, ı -> I)."""
    return text.replace("i", "İ").replace("ı", "I").upper()


def _labels(doc: Doc) -> dict[str, str]:
    if doc.lang == "tr":
        return {
            "doc_no": "Doküman No",
            "date": "Yayın Tarihi",
            "page": "Sayfa",
            "class": "Gizlilik",
        }
    return {
        "doc_no": "Document No",
        "date": "Issue Date",
        "page": "Page",
        "class": "Classification",
    }


def _date_str(doc: Doc) -> str:
    if doc.lang == "tr":
        return doc.date.strftime("%d.%m.%Y")
    return doc.date.isoformat()


def _meta_lines(doc: Doc) -> list[tuple[str, str]]:
    lab = _labels(doc)
    lines: list[tuple[str, str]] = []
    if doc.doc_no:
        lines.append((lab["doc_no"], doc.doc_no))
    lines.extend(doc.meta)
    lines.append((lab["date"], _date_str(doc)))
    lines.append((lab["class"], doc.label()))
    return lines


def _fonts() -> tuple[str, str]:
    import matplotlib

    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    return str(base / "DejaVuSans.ttf"), str(base / "DejaVuSans-Bold.ttf")


# ── PDF ──────────────────────────────────────────────────────────────────────
_PDF_READY = False


def _pdf_setup() -> None:
    global _PDF_READY
    if _PDF_READY:
        return
    from reportlab import rl_config
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    rl_config.invariant = 1  # fixed /CreationDate and document ID
    regular, bold = _fonts()
    pdfmetrics.registerFont(TTFont("DejaVu", regular))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
    addMapping("DejaVu", 0, 0, "DejaVu")
    addMapping("DejaVu", 1, 0, "DejaVu-Bold")
    addMapping("DejaVu", 0, 1, "DejaVu")
    addMapping("DejaVu", 1, 1, "DejaVu-Bold")
    _PDF_READY = True


def render_pdf(doc: Doc, out: Path) -> None:
    _pdf_setup()
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        ListFlowable,
        ListItem,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        TableStyle,
    )
    from reportlab.platypus import (
        PageBreak as RLPageBreak,
    )
    from reportlab.platypus import (
        Table as RLTable,
    )

    lab = _labels(doc)
    accent = colors.HexColor("#1F3A5F")
    base = ParagraphStyle(
        "base", fontName="DejaVu", fontSize=9.6, leading=13.4, alignment=TA_LEFT, spaceAfter=5
    )
    styles = {
        "company": ParagraphStyle(
            "company",
            parent=base,
            fontName="DejaVu-Bold",
            fontSize=8.5,
            textColor=accent,
            spaceAfter=2,
        ),
        "title": ParagraphStyle(
            "title",
            parent=base,
            fontName="DejaVu-Bold",
            fontSize=17,
            leading=21,
            spaceAfter=4,
            textColor=accent,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#444444"),
            spaceAfter=8,
        ),
        "meta": ParagraphStyle("meta", parent=base, fontSize=8.4, leading=11, spaceAfter=0),
        1: ParagraphStyle(
            "h1",
            parent=base,
            fontName="DejaVu-Bold",
            fontSize=12.5,
            leading=16,
            spaceBefore=9,
            spaceAfter=4,
            textColor=accent,
        ),
        2: ParagraphStyle(
            "h2",
            parent=base,
            fontName="DejaVu-Bold",
            fontSize=10.8,
            leading=14,
            spaceBefore=6,
            spaceAfter=3,
        ),
        3: ParagraphStyle(
            "h3",
            parent=base,
            fontName="DejaVu-Bold",
            fontSize=9.8,
            leading=13,
            spaceBefore=4,
            spaceAfter=2,
        ),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.4, leading=10.6, spaceAfter=0),
        "cellh": ParagraphStyle(
            "cellh",
            parent=base,
            fontName="DejaVu-Bold",
            fontSize=8.4,
            leading=10.6,
            spaceAfter=0,
            textColor=colors.white,
        ),
        "caption": ParagraphStyle(
            "caption",
            parent=base,
            fontSize=8.2,
            leading=10.5,
            textColor=colors.HexColor("#555555"),
            spaceBefore=2,
            spaceAfter=7,
        ),
    }
    width = A4[0] - 40 * mm

    story: list = [
        Paragraph(escape(COMPANY_CAPS if doc.lang == "tr" else COMPANY_EN), styles["company"]),
        Paragraph(escape(doc.title), styles["title"]),
    ]
    if doc.subtitle:
        story.append(Paragraph(escape(doc.subtitle), styles["subtitle"]))
    meta = [
        [Paragraph(escape(k), styles["meta"]), Paragraph(escape(v), styles["meta"])]
        for k, v in _meta_lines(doc)
    ]
    mt = RLTable(meta, colWidths=[38 * mm, width - 38 * mm], hAlign="LEFT")
    mt.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF2F7")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9D3DF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story += [mt, Spacer(1, 8)]

    for block in doc.blocks:
        if isinstance(block, H):
            story.append(Paragraph(escape(block.text), styles[min(block.level, 3)]))
        elif isinstance(block, P):
            story.append(Paragraph(escape(block.text), base))
        elif isinstance(block, Bullets):
            items = [ListItem(Paragraph(escape(t), base), leftIndent=12) for t in block.items]
            story.append(
                ListFlowable(
                    items,
                    bulletType="1" if block.numbered else "bullet",
                    start=1 if block.numbered else None,
                    bulletFontName="DejaVu",
                    bulletFontSize=8.5,
                    leftIndent=12,
                )
            )
        elif isinstance(block, Table):
            n = len(block.header)
            rel = block.widths or tuple(1.0 for _ in range(n))
            total = sum(rel)
            col_widths = [width * w / total for w in rel]
            data = [[Paragraph(escape(c), styles["cellh"]) for c in block.header]]
            data += [[Paragraph(escape(str(c)), styles["cell"]) for c in row] for row in block.rows]
            t = RLTable(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), accent),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#F4F6F9")],
                        ),
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B8C2CF")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(Spacer(1, 3))
            story.append(t)
            if block.caption:
                story.append(Paragraph(escape(block.caption), styles["caption"]))
            else:
                story.append(Spacer(1, 7))
        elif isinstance(block, PageBreak):
            story.append(RLPageBreak())

    footer = f"{COMPANY_TR} · {doc.doc_no or doc.title} · {doc.label()}"

    def on_page(canvas, _doc):
        canvas.saveState()
        canvas.setFont("DejaVu", 7.2)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(20 * mm, 11 * mm, footer)
        canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, f"{lab['page']} {_doc.page}")
        canvas.restoreState()

    out.parent.mkdir(parents=True, exist_ok=True)
    tpl = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=doc.title,
        author="",
        subject="",
        creator="",
        producer="",
        keywords="",
    )
    tpl.build(story, onFirstPage=on_page, onLaterPages=on_page)


# ── OOXML determinism ────────────────────────────────────────────────────────
def _iso(d: dt.date) -> str:
    return f"{d.isoformat()}T09:00:00Z"


def normalize_ooxml(path: Path, date: dt.date) -> None:
    """Rewrite an OOXML archive with fixed timestamps and no author metadata so
    rebuilding yields byte-identical files."""
    src = path.read_bytes()
    stamp = (date.year, date.month, date.day, 9, 0, 0)
    buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(src)) as zin,
        zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "docProps/core.xml":
                xml = data.decode("utf-8")
                for tag in ("dcterms:created", "dcterms:modified"):
                    xml = re.sub(rf"(<{tag}[^>]*>)[^<]*(</{tag}>)", rf"\g<1>{_iso(date)}\g<2>", xml)
                for tag in ("dc:creator", "cp:lastModifiedBy"):
                    xml = re.sub(rf"<{tag}>[^<]*</{tag}>", f"<{tag}></{tag}>", xml)
                    xml = re.sub(rf"<{tag}\s*/>", f"<{tag}></{tag}>", xml)
                xml = re.sub(
                    r"<cp:revision>[^<]*</cp:revision>", "<cp:revision>1</cp:revision>", xml
                )
                data = xml.encode("utf-8")
            zi = zipfile.ZipInfo(info.filename, date_time=stamp)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            zout.writestr(zi, data)
    path.write_bytes(buf.getvalue())


# ── DOCX ─────────────────────────────────────────────────────────────────────
def render_docx(doc: Doc, out: Path) -> None:
    import docx
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    d = docx.Document()
    styles = d.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10.5)
    cp = d.core_properties
    cp.author = ""
    cp.last_modified_by = ""
    cp.title = doc.title
    cp.subject = ""
    cp.keywords = ""
    cp.comments = ""
    cp.category = ""
    cp.revision = 1
    stamp = dt.datetime(doc.date.year, doc.date.month, doc.date.day, 9, 0, 0)
    cp.created = stamp
    cp.modified = stamp

    company = d.add_paragraph()
    run = company.add_run(COMPANY_CAPS if doc.lang == "tr" else COMPANY_EN)
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    d.add_heading(doc.title, level=0)
    if doc.subtitle:
        sp = d.add_paragraph()
        sr = sp.add_run(doc.subtitle)
        sr.italic = True
    for key, value in _meta_lines(doc):
        mp = d.add_paragraph()
        mp.paragraph_format.space_after = Pt(0)
        kr = mp.add_run(f"{key}: ")
        kr.bold = True
        kr.font.size = Pt(9)
        vr = mp.add_run(value)
        vr.font.size = Pt(9)
    d.add_paragraph()

    def shade(cell, hex_fill: str) -> None:
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_fill)
        tc_pr.append(shd)

    for block in doc.blocks:
        if isinstance(block, H):
            d.add_heading(block.text, level=min(block.level, 3))
        elif isinstance(block, P):
            d.add_paragraph(block.text)
        elif isinstance(block, Bullets):
            style = "List Number" if block.numbered else "List Bullet"
            for item in block.items:
                d.add_paragraph(item, style=style)
        elif isinstance(block, Table):
            t = d.add_table(rows=1, cols=len(block.header))
            t.style = "Table Grid"
            t.alignment = WD_TABLE_ALIGNMENT.LEFT
            for i, text in enumerate(block.header):
                cell = t.rows[0].cells[i]
                cell.text = ""
                r = cell.paragraphs[0].add_run(text)
                r.bold = True
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                shade(cell, "1F3A5F")
            for row in block.rows:
                cells = t.add_row().cells
                for i, text in enumerate(row):
                    cells[i].text = str(text)
            if block.caption:
                cap = d.add_paragraph()
                cr = cap.add_run(block.caption)
                cr.italic = True
                cr.font.size = Pt(9)
            else:
                d.add_paragraph()
        elif isinstance(block, PageBreak):
            d.add_page_break()

    footer = d.sections[0].footer.paragraphs[0]
    footer.text = f"{COMPANY_TR} · {doc.doc_no or doc.title} · {doc.label()}"
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out))
    normalize_ooxml(out, doc.date)


# ── XLSX ─────────────────────────────────────────────────────────────────────
def render_xlsx(doc: Doc, out: Path) -> None:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    props = wb.properties
    props.creator = ""
    props.lastModifiedBy = ""
    props.title = doc.title
    stamp = dt.datetime(doc.date.year, doc.date.month, doc.date.day, 9, 0, 0)
    props.created = stamp
    props.modified = stamp

    head_fill = PatternFill("solid", fgColor="1F3A5F")
    for sheet in doc.sheets:
        ws = wb.create_sheet(sheet.name)
        r = 1
        if sheet.title:
            ws.cell(row=1, column=1, value=sheet.title).font = Font(bold=True, size=13)
            r = 3
        header_row = r
        for c, text in enumerate(sheet.header, start=1):
            cell = ws.cell(row=r, column=c, value=text)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for row in sheet.rows:
            r += 1
            for c, value in enumerate(row, start=1):
                cell = ws.cell(row=r, column=c, value=value)
                if isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 1000:
                    cell.number_format = "#,##0"
        if sheet.notes:
            r += 1
            for note in sheet.notes:
                r += 1
                ws.cell(row=r, column=1, value=note).font = Font(italic=True, color="555555")
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
        for c in range(1, len(sheet.header) + 1):
            if sheet.widths and c <= len(sheet.widths):
                w = sheet.widths[c - 1]
            else:
                values = [sheet.header[c - 1]] + [
                    str(row[c - 1]) for row in sheet.rows if c - 1 < len(row)
                ]
                w = min(48, max(10, max(len(v) for v in values) + 2))
            ws.column_dimensions[get_column_letter(c)].width = w
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    normalize_ooxml(out, doc.date)


# ── PPTX ─────────────────────────────────────────────────────────────────────
def render_pptx(doc: Doc, out: Path) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Emu, Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    cp = prs.core_properties
    cp.author = ""
    cp.last_modified_by = ""
    cp.title = doc.title
    cp.revision = 1
    stamp = dt.datetime(doc.date.year, doc.date.month, doc.date.day, 9, 0, 0)
    cp.created = stamp
    cp.modified = stamp
    accent = RGBColor(0x1F, 0x3A, 0x5F)

    for index, s in enumerate(doc.slides):
        if index == 0:
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = s.title
            slide.shapes.title.width = prs.slide_width - Inches(1.6)
            slide.shapes.title.left = Inches(0.8)
            sub = slide.placeholders[1]
            sub.left, sub.width = Inches(0.8), prs.slide_width - Inches(1.6)
            sub.text = s.subtitle or ""
        else:
            slide = prs.slides.add_slide(prs.slide_layouts[5])  # title only
            title = slide.shapes.title
            title.text = s.title
            title.left, title.top = Inches(0.6), Inches(0.35)
            title.width, title.height = prs.slide_width - Inches(1.2), Inches(1.0)
            for p in title.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(30)
                    run.font.bold = True
                    run.font.color.rgb = accent
            top = Inches(1.5)
            if s.bullets:
                height = Inches(2.3) if s.table else Inches(5.4)
                box = slide.shapes.add_textbox(
                    Inches(0.7), top, prs.slide_width - Inches(1.4), height
                )
                tf = box.text_frame
                tf.word_wrap = True
                for i, text in enumerate(s.bullets):
                    para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    para.text = f"• {text}"
                    para.space_after = Pt(6)
                    for run in para.runs:
                        run.font.size = Pt(17 if s.table else 19)
                top = Emu(top + height + Inches(0.1))
            if s.table:
                rows, cols = len(s.table.rows) + 1, len(s.table.header)
                height = Inches(0.42) * rows
                gt = slide.shapes.add_table(
                    rows, cols, Inches(0.7), top, prs.slide_width - Inches(1.4), height
                ).table
                for c, text in enumerate(s.table.header):
                    gt.cell(0, c).text = text
                for r, row in enumerate(s.table.rows, start=1):
                    for c, text in enumerate(row):
                        gt.cell(r, c).text = str(text)
                for r in range(rows):
                    for c in range(cols):
                        for para in gt.cell(r, c).text_frame.paragraphs:
                            for run in para.runs:
                                run.font.size = Pt(14)
        if s.notes:
            slide.notes_slide.notes_text_frame.text = s.notes
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out))
    normalize_ooxml(out, doc.date)


# ── Markdown / plain text ────────────────────────────────────────────────────
def _md_cell(text: object) -> str:
    return str(text).replace("|", "\\|")


def render_md(doc: Doc, out: Path) -> None:
    lines = [f"# {doc.title}", ""]
    if doc.subtitle:
        lines += [doc.subtitle, ""]
    for key, value in _meta_lines(doc):
        lines.append(f"- {key}: {value}")
    lines.append("")
    for block in doc.blocks:
        if isinstance(block, H):
            lines += [f"{'#' * (min(block.level, 3) + 1)} {block.text}", ""]
        elif isinstance(block, P):
            lines += [block.text, ""]
        elif isinstance(block, Bullets):
            for i, item in enumerate(block.items, start=1):
                lines.append(f"{i}. {item}" if block.numbered else f"- {item}")
            lines.append("")
        elif isinstance(block, Table):
            lines.append("| " + " | ".join(_md_cell(c) for c in block.header) + " |")
            lines.append("| " + " | ".join("---" for _ in block.header) + " |")
            for row in block.rows:
                lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
            lines.append("")
            if block.caption:
                lines += [block.caption, ""]
        elif isinstance(block, PageBreak):
            lines += ["---", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def render_txt(doc: Doc, out: Path) -> None:
    title = tr_upper(doc.title) if doc.lang == "tr" else doc.title.upper()
    lines = [title, "=" * min(78, len(doc.title)), ""]
    if doc.subtitle:
        lines += [doc.subtitle, ""]
    for key, value in _meta_lines(doc):
        lines.append(f"{key}: {value}")
    lines.append("")
    for block in doc.blocks:
        if isinstance(block, H):
            under = "-" if block.level == 1 else "."
            lines += ["", block.text, under * min(78, len(block.text)), ""]
        elif isinstance(block, P):
            lines += [textwrap.fill(block.text, 78), ""]
        elif isinstance(block, Bullets):
            for i, item in enumerate(block.items, start=1):
                prefix = f"  {i}. " if block.numbered else "  - "
                lines.append(
                    textwrap.fill(
                        item, 78, initial_indent=prefix, subsequent_indent=" " * len(prefix)
                    )
                )
            lines.append("")
        elif isinstance(block, Table):
            rows = [list(block.header)] + [[str(c) for c in r] for r in block.rows]
            widths = [max(len(r[i]) for r in rows) for i in range(len(block.header))]
            for n, row in enumerate(rows):
                lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip())
                if n == 0:
                    lines.append("  ".join("-" * w for w in widths))
            lines.append("")
            if block.caption:
                lines += [block.caption, ""]
        elif isinstance(block, PageBreak):
            lines += ["", "-" * 78, ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ── PNG (scanned memo, exercised through OCR) ────────────────────────────────
def render_png(doc: Doc, out: Path) -> None:
    """A one-page memo rendered as a slightly skewed, lightly noisy 'scan'."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    regular, bold = _fonts()
    W, H_ = 1654, 2339  # A4 at 200 dpi
    img = Image.new("L", (W, H_), 246)
    draw = ImageDraw.Draw(img)
    f_body = ImageFont.truetype(regular, 34)
    f_bold = ImageFont.truetype(bold, 36)
    f_title = ImageFont.truetype(bold, 50)
    f_small = ImageFont.truetype(regular, 28)
    x, y = 150, 150
    draw.text((x, y), COMPANY_CAPS, font=f_bold, fill=30)
    y += 52
    draw.text(
        (x, y),
        "Büyükdere Caddesi No: 214, Kat 9-11, Maslak, Sarıyer / İstanbul",
        font=f_small,
        fill=60,
    )
    y += 50
    draw.line((x, y, W - 150, y), fill=40, width=3)
    y += 50
    draw.text((x, y), doc.title, font=f_title, fill=20)
    y += 90
    for key, value in _meta_lines(doc):
        draw.text((x, y), f"{key}: {value}", font=f_body, fill=25)
        y += 50
    y += 30
    draw.line((x, y, W - 150, y), fill=90, width=2)
    y += 45
    for block in doc.blocks:
        if isinstance(block, H):
            y += 10
            draw.text((x, y), block.text, font=f_bold, fill=20)
            y += 58
        elif isinstance(block, P):
            for line in textwrap.wrap(block.text, 62):
                draw.text((x, y), line, font=f_body, fill=25)
                y += 50
            y += 24
        elif isinstance(block, Bullets):
            for i, item in enumerate(block.items, start=1):
                prefix = f"{i}. " if block.numbered else "- "
                wrapped = textwrap.wrap(item, 58)
                for j, line in enumerate(wrapped):
                    lead = prefix if j == 0 else "   "
                    draw.text((x + 20, y), lead + line, font=f_body, fill=25)
                    y += 50
            y += 24
    rng = random.Random(20261102)
    px = img.load()
    for _ in range(9000):  # light toner speckle
        px[rng.randrange(W), rng.randrange(H_)] = rng.randrange(120, 200)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img = img.rotate(0.35, resample=Image.BICUBIC, fillcolor=246)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), format="PNG", optimize=True)


RENDERERS = {
    ".pdf": render_pdf,
    ".docx": render_docx,
    ".xlsx": render_xlsx,
    ".pptx": render_pptx,
    ".md": render_md,
    ".txt": render_txt,
    ".png": render_png,
}
