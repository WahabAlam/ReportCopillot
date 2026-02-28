from __future__ import annotations

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from pathlib import Path
import re


def _get_or_add_style(styles, name: str, **kwargs):
    if name in styles:
        return styles[name]
    styles.add(ParagraphStyle(name=name, **kwargs))
    return styles[name]


def _safe_text(s: str) -> str:
    return (s or "").strip()


def _lines_to_paragraphs(text: str, style):
    parts = []
    for line in _safe_text(text).splitlines():
        if line.strip():
            parts.append(Paragraph(line.strip(), style))
            parts.append(Spacer(1, 6))
    if not parts:
        parts.append(Paragraph("—", style))
    return parts


def _is_header_line(line: str) -> bool:
    s = (line or "").strip()
    if not s.endswith(":"):
        return False
    head = s[:-1].strip()
    return bool(re.fullmatch(r"[A-Za-z0-9 &/\-\(\)]{2,80}", head))


def _is_md_table_row(line: str) -> bool:
    s = (line or "").strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _is_md_separator_row(line: str) -> bool:
    s = (line or "").strip().replace(" ", "")
    if not _is_md_table_row(s):
        return False
    cells = [c for c in s.strip("|").split("|")]
    if not cells:
        return False
    for c in cells:
        if not c or set(c) - set("-:"):
            return False
    return True


def _parse_md_row(line: str) -> list[str]:
    return [c.strip() for c in (line or "").strip().strip("|").split("|")]


def _build_table(data: list[list[str]], header: bool = True) -> Table:
    t = Table(data, repeatRows=1 if header else 0)
    base = [
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        base.append(("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke))
        base.append(("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"))
    t.setStyle(TableStyle(base))
    return t


def _append_report_text(story, report_text: str, h_style, body_style):
    lines = (report_text or "").splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        s = ln.strip()
        if not s:
            i += 1
            continue

        # Render markdown tables as native PDF tables
        if _is_md_table_row(s):
            rows: list[list[str]] = []
            while i < len(lines) and _is_md_table_row(lines[i].strip()):
                row = lines[i].strip()
                if not _is_md_separator_row(row):
                    rows.append(_parse_md_row(row))
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                for r in rows:
                    if len(r) < width:
                        r.extend([""] * (width - len(r)))
                story.append(_build_table(rows, header=True))
                story.append(Spacer(1, 8))
            continue

        # Promote template section headers inside report body
        if _is_header_line(s):
            story.append(Paragraph(s[:-1], h_style))
            i += 1
            continue

        story.append(Paragraph(s, body_style))
        story.append(Spacer(1, 4))
        i += 1


def _figure_note(title: str) -> str:
    tl = (title or "").lower()
    if "time" in tl:
        return "Insight: use this to assess trend direction and rate of change over the full run."
    if "histogram" in tl:
        return "Insight: use this to assess distribution shape, spread, and concentration."
    if "box" in tl:
        return "Insight: use this to inspect median, interquartile range, and potential outliers."
    return "Insight: relate this figure directly to a claim made in Results or Discussion."


def build_submission_pdf(
    out_path: str,
    meta: dict,
    source_summary: str,
    report_text: str,
    review_text: str,
    data_preview: list[dict] | None,
    plot_paths: dict | None,
):
    out_path = str(out_path)
    plot_paths = plot_paths or {}
    data_preview = data_preview or []

    styles = getSampleStyleSheet()
    title_style = _get_or_add_style(
        styles,
        "TitleX",
        parent=styles["Title"],
        fontSize=20,
        leading=24,
        spaceAfter=12,
    )
    h_style = _get_or_add_style(
        styles,
        "HeaderX",
        parent=styles["Heading2"],
        fontSize=13,
        leading=16,
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = _get_or_add_style(
        styles,
        "BodyX",
        parent=styles["Normal"],
        fontSize=10.5,
        leading=14,
        spaceAfter=6,
    )
    cap_style = _get_or_add_style(
        styles,
        "CaptionX",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6,
    )

    doc = SimpleDocTemplate(out_path, pagesize=letter, rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54)
    story = []

    # Cover
    story.append(Paragraph(_safe_text(meta.get("title", "Report")), title_style))
    cover_rows = [
        ["Template", _safe_text(meta.get("template", ""))],
        ["Name", _safe_text(meta.get("name", ""))],
        ["Course", _safe_text(meta.get("course", ""))],
        ["Group", _safe_text(meta.get("group", ""))],
        ["Date", _safe_text(meta.get("date", ""))],
    ]
    cover_table = Table(cover_rows, colWidths=[1.3 * inch, 4.9 * inch])
    cover_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(Spacer(1, 12))
    story.append(cover_table)
    story.append(PageBreak())

    # Source summary
    story.append(Paragraph("Source / Instructions Summary", h_style))
    story.extend(_lines_to_paragraphs(source_summary, body_style))

    # Data preview (optional)
    if data_preview:
        story.append(Paragraph("Data Preview (first rows)", h_style))
        cols = list(data_preview[0].keys())
        table_data = [cols]
        for row in data_preview[:10]:
            table_data.append([str(row.get(c, "")) for c in cols])

        t = _build_table(table_data, header=True)
        story.append(t)

    story.append(PageBreak())

    # Report
    story.append(Paragraph("Report", h_style))
    _append_report_text(story, report_text, h_style, body_style)

    # ✅ Review (only if provided)
    if _safe_text(review_text):
        story.append(PageBreak())
        story.append(Paragraph("Reviewer Feedback", h_style))
        story.extend(_lines_to_paragraphs(review_text, body_style))

    # Plots (optional)
    if plot_paths:
        story.append(PageBreak())
        story.append(Paragraph("Figures", h_style))
        for title, p in plot_paths.items():
            path = Path(p)
            if not path.exists():
                continue
            story.append(Paragraph(title, body_style))
            img = Image(str(path))
            img.drawWidth = 6.5 * inch
            img.drawHeight = 4.0 * inch
            story.append(img)
            story.append(Paragraph(_figure_note(title), cap_style))
            story.append(Spacer(1, 12))

    doc.build(story)
    return out_path
