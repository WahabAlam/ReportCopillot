"""Utility helpers for pdf report."""

from __future__ import annotations

from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
    ListFlowable,
    ListItem,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from pathlib import Path
from utils.retrieval import extract_source_tags
from utils.sections import split_by_headers
import re


def _get_or_add_style(styles, name: str, **kwargs):
    # Reuse styles when present to avoid duplicate-name errors in ReportLab.
    if name in styles:
        return styles[name]
    styles.add(ParagraphStyle(name=name, **kwargs))
    return styles[name]


def _safe_text(s: str) -> str:
    # Normalize nullable text fields before rendering.
    return (s or "").strip()


def _escape_para_text(s: str) -> str:
    # ReportLab Paragraph supports simple markup, so escape angle/ampersand chars.
    text = _safe_text(s)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _lines_to_paragraphs(text: str, style):
    # Convert plain multiline text into paragraph + spacer pairs.
    parts = []
    for line in _safe_text(text).splitlines():
        if line.strip():
            parts.append(Paragraph(line.strip(), style))
            parts.append(Spacer(1, 6))
    if not parts:
        parts.append(Paragraph("—", style))
    return parts


def _is_header_line(line: str) -> bool:
    # Heuristic for "Section Name:" style headings in generated report text.
    s = (line or "").strip()
    if not s.endswith(":"):
        return False
    head = s[:-1].strip()
    return bool(re.fullmatch(r"[A-Za-z0-9 &/\-\(\)]{2,80}", head))


def _is_md_table_row(line: str) -> bool:
    # Lightweight markdown table row detector.
    s = (line or "").strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _is_md_separator_row(line: str) -> bool:
    # Detect markdown separator lines like |---|:---:| to skip them in table data.
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
    # Parse one markdown row into clean cell strings.
    return [c.strip() for c in (line or "").strip().strip("|").split("|")]


DEFAULT_THEME = {
    "font_name": "Helvetica",
    "title_size": 20,
    "heading_size": 13,
    "body_size": 10.5,
    "caption_size": 9,
    "title_leading": 24,
    "heading_leading": 16,
    "body_leading": 14,
    "caption_leading": 12,
    "heading_color": "#1e293b",
    "caption_color": "#334155",
    "table_header_bg": "#f1f5f9",
    "table_grid": "#94a3b8",
    "table_alt_row_bg": "#f8fafc",
}

# Layout constants are in points/inches and tuned for US Letter output.
DEFAULT_LAYOUT = {
    "left_margin": 54,
    "right_margin": 54,
    "top_margin": 54,
    "bottom_margin": 54,
    "data_preview_rows": 10,
    "image_max_width_in": 6.4,
    "image_max_height_in": 4.8,
    "plot_width_in": 6.5,
    "plot_height_in": 4.0,
    "footer_font_size": 8,
}

DEFAULT_PRINT_PROFILE = "standard"
# Print profiles let users trade off density/readability without editing templates.
PRINT_PROFILES = {
    "standard": {
        "label": "Standard",
        "description": "Balanced readability and page count for general submission.",
        "theme": {},
        "layout": {},
    },
    "dense": {
        "label": "Dense",
        "description": "Fits more content per page with tighter spacing.",
        "theme": {
            "title_size": 18,
            "title_leading": 21,
            "heading_size": 12,
            "heading_leading": 14,
            "body_size": 9.5,
            "body_leading": 12,
            "caption_size": 8.5,
            "caption_leading": 10,
        },
        "layout": {
            "left_margin": 44,
            "right_margin": 44,
            "top_margin": 46,
            "bottom_margin": 46,
            "data_preview_rows": 14,
            "image_max_width_in": 6.8,
            "image_max_height_in": 4.3,
            "plot_width_in": 6.8,
            "plot_height_in": 3.7,
        },
    },
    "presentation": {
        "label": "Presentation",
        "description": "Larger typography and visuals for easier on-screen reading.",
        "theme": {
            "title_size": 22,
            "title_leading": 26,
            "heading_size": 14,
            "heading_leading": 18,
            "body_size": 11.5,
            "body_leading": 15.5,
            "caption_size": 10,
            "caption_leading": 13,
        },
        "layout": {
            "left_margin": 60,
            "right_margin": 60,
            "top_margin": 60,
            "bottom_margin": 60,
            "data_preview_rows": 8,
            "image_max_width_in": 5.9,
            "image_max_height_in": 5.0,
            "plot_width_in": 5.9,
            "plot_height_in": 4.3,
        },
    },
    "print_safe": {
        "label": "Print-Safe",
        "description": "High-contrast grayscale-friendly styling for physical print.",
        "theme": {
            "heading_color": "#111827",
            "caption_color": "#1f2937",
            "table_header_bg": "#e5e7eb",
            "table_grid": "#6b7280",
            "table_alt_row_bg": "#f9fafb",
        },
        "layout": {
            "left_margin": 54,
            "right_margin": 54,
            "top_margin": 54,
            "bottom_margin": 54,
            "data_preview_rows": 10,
            "image_max_width_in": 6.4,
            "image_max_height_in": 4.8,
            "plot_width_in": 6.5,
            "plot_height_in": 4.0,
        },
    },
}
PRINT_PROFILE_KEYS = tuple(PRINT_PROFILES.keys())


def _merge_theme(theme: dict | None) -> dict:
    # Template and profile overrides layer on top of global defaults.
    out = dict(DEFAULT_THEME)
    if isinstance(theme, dict):
        out.update({k: v for k, v in theme.items() if v is not None})
    return out


def _merge_layout(layout: dict | None) -> dict:
    # Layout merge mirrors theme merge for predictable final dimensions.
    out = dict(DEFAULT_LAYOUT)
    if isinstance(layout, dict):
        out.update({k: v for k, v in layout.items() if v is not None})
    return out


def normalize_print_profile(value: str | None) -> str:
    # Unknown values fall back to default instead of failing PDF build.
    key = (value or "").strip().lower()
    if key in PRINT_PROFILES:
        return key
    return DEFAULT_PRINT_PROFILE


def get_print_profile_options() -> list[dict]:
    # UI-friendly projection of profile metadata.
    return [
        {
            "key": key,
            "label": cfg.get("label", key),
            "description": cfg.get("description", ""),
        }
        for key, cfg in PRINT_PROFILES.items()
    ]


def _build_table(data: list[list[str]], header: bool = True, theme: dict | None = None) -> Table:
    # Apply consistent table styling across cover/data/report markdown tables.
    theme = _merge_theme(theme)
    grid_color = colors.HexColor(str(theme["table_grid"]))
    header_bg = colors.HexColor(str(theme["table_header_bg"]))
    alt_bg = colors.HexColor(str(theme["table_alt_row_bg"]))
    font_name = str(theme["font_name"])
    t = Table(data, repeatRows=1 if header else 0)
    base = [
        ("BOX", (0, 0), (-1, -1), 0.6, grid_color),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, grid_color),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        base.append(("BACKGROUND", (0, 0), (-1, 0), header_bg))
        base.append(("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"))
        if len(data) > 2:
            for row in range(1, len(data)):
                if row % 2 == 0:
                    base.append(("BACKGROUND", (0, row), (-1, row), alt_bg))
    t.setStyle(TableStyle(base))
    return t


def _is_bullet_line(line: str) -> bool:
    # Supports -, *, and bullet symbol list markers.
    return bool(re.match(r"^\s*[-*•]\s+\S+", line or ""))


def _is_numbered_line(line: str) -> bool:
    # Supports simple "1. Item" numbering.
    return bool(re.match(r"^\s*\d+\.\s+\S+", line or ""))


def _strip_list_prefix(line: str) -> str:
    # Strip both bullet and numbered prefixes for normalized list item text.
    s = (line or "").strip()
    s = re.sub(r"^[-*•]\s+", "", s)
    s = re.sub(r"^\d+\.\s+", "", s)
    return s.strip()


def _normalize_section_name(value: str) -> str:
    # Normalize section names for fuzzy matching (case/punctuation insensitive).
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _pick_image_section(asset: dict, report_headers: list[str]) -> str | None:
    # Resolve an image's preferred section using explicit target then suggestions.
    if not report_headers:
        return None

    header_lookup = {_normalize_section_name(h): h for h in report_headers}
    candidates: list[str] = []
    target = (asset.get("target_section") or "").strip()
    if target:
        candidates.append(target)
    for v in (asset.get("suggested_sections") or []):
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())

    for c in candidates:
        key = _normalize_section_name(c)
        if key in header_lookup:
            return header_lookup[key]
    return None


def _group_images_by_section(uploaded_images: list[dict], report_headers: list[str]) -> tuple[dict[str, list[dict]], list[dict]]:
    # Split images into section-assigned and unassigned buckets.
    grouped: dict[str, list[dict]] = {h: [] for h in (report_headers or [])}
    remainder: list[dict] = []
    for asset in (uploaded_images or []):
        if not isinstance(asset, dict):
            continue
        section = _pick_image_section(asset, report_headers or [])
        if section and section in grouped:
            grouped[section].append(asset)
        else:
            remainder.append(asset)
    return grouped, remainder


def _asset_figure_title(asset: dict, figure_index: int) -> str:
    # Build stable figure titles with user title > filename > auto label fallback.
    label = _safe_text(asset.get("label", "")) or f"Image {figure_index}"
    user_title = _safe_text(asset.get("title", ""))
    filename = _safe_text(asset.get("filename", ""))
    detail = user_title or filename or label
    return f"Figure {figure_index}. {detail}"


def _append_uploaded_image_block(
    story: list,
    asset: dict,
    *,
    figure_index: int,
    body_style,
    cap_style,
    max_width: float,
    max_height: float,
) -> bool:
    # Append image + optional caption; returns False when path is missing/invalid.
    p = asset.get("path", "")
    path = Path(p)
    if not p or not path.exists():
        return False

    parts = [Paragraph(_asset_figure_title(asset, figure_index), body_style)]
    try:
        # Scale while preserving aspect ratio and never upscaling tiny images.
        img = Image(str(path))
        w = float(getattr(img, "imageWidth", max_width))
        h = float(getattr(img, "imageHeight", max_height))
        if w > 0 and h > 0:
            scale = min(max_width / w, max_height / h, 1.0)
            img.drawWidth = w * scale
            img.drawHeight = h * scale
        else:
            img.drawWidth = max_width
            img.drawHeight = max_height
        parts.append(img)
    except Exception:
        # Keep build resilient if one image cannot be decoded.
        parts.append(Paragraph("Could not render this image file.", cap_style))

    caption = _safe_text(asset.get("caption", ""))
    if caption:
        parts.append(Paragraph(caption, cap_style))
    story.append(KeepTogether(parts))
    story.append(Spacer(1, 12))
    return True


def _append_report_text(story, report_text: str, h_style, body_style, theme: dict | None = None):
    # Parse generated plain text into richer PDF flowables (tables/lists/headers/paragraphs).
    theme = _merge_theme(theme)
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
                story.append(_build_table(rows, header=True, theme=theme))
                story.append(Spacer(1, 8))
            continue

        # Promote template section headers inside report body
        if _is_header_line(s):
            story.append(Paragraph(s[:-1], h_style))
            i += 1
            continue

        if _is_bullet_line(s):
            # Consume contiguous bullet lines as one list block.
            items = []
            while i < len(lines) and _is_bullet_line(lines[i].strip()):
                items.append(_strip_list_prefix(lines[i]))
                i += 1
            list_items = [ListItem(Paragraph(it, body_style)) for it in items if it.strip()]
            if list_items:
                story.append(ListFlowable(list_items, bulletType="bullet", leftIndent=18))
                story.append(Spacer(1, 6))
            continue

        if _is_numbered_line(s):
            # Consume contiguous numbered lines as one ordered list block.
            items = []
            while i < len(lines) and _is_numbered_line(lines[i].strip()):
                items.append(_strip_list_prefix(lines[i]))
                i += 1
            list_items = [ListItem(Paragraph(it, body_style)) for it in items if it.strip()]
            if list_items:
                story.append(ListFlowable(list_items, bulletType="1", leftIndent=18))
                story.append(Spacer(1, 6))
            continue

        # Otherwise, collapse contiguous non-empty prose lines into one paragraph.
        paragraph_lines = [s]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt:
                break
            if _is_header_line(nxt) or _is_md_table_row(nxt) or _is_bullet_line(nxt) or _is_numbered_line(nxt):
                break
            paragraph_lines.append(nxt)
            i += 1
        story.append(Paragraph(" ".join(paragraph_lines), body_style))
        story.append(Spacer(1, 4))
        continue


def _figure_note(title: str) -> str:
    # Minimal heuristic captions to prompt interpretation in Results/Discussion.
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
    uploaded_images: list[dict] | None = None,
    source_chunks: list[dict] | None = None,
    include_source_appendix: bool = True,
    theme: dict | None = None,
    report_headers: list[str] | None = None,
    print_profile: str = DEFAULT_PRINT_PROFILE,
):
    # Main PDF assembly entrypoint used by both initial build and rebuild flows.
    out_path = str(out_path)
    profile_key = normalize_print_profile(print_profile)
    profile_cfg = PRINT_PROFILES.get(profile_key, PRINT_PROFILES[DEFAULT_PRINT_PROFILE])

    # Profile theme overrides template theme; template still controls base look-and-feel.
    merged_theme = dict(theme or {})
    merged_theme.update(profile_cfg.get("theme", {}) or {})
    theme = _merge_theme(merged_theme)

    # Convert layout values into concrete render dimensions.
    layout = _merge_layout(profile_cfg.get("layout", {}) or {})
    image_max_width = float(layout.get("image_max_width_in", 6.4)) * inch
    image_max_height = float(layout.get("image_max_height_in", 4.8)) * inch
    plot_width = float(layout.get("plot_width_in", 6.5)) * inch
    plot_height = float(layout.get("plot_height_in", 4.0)) * inch
    data_preview_rows = int(layout.get("data_preview_rows", 10))
    footer_font_size = float(layout.get("footer_font_size", 8))

    plot_paths = plot_paths or {}
    uploaded_images = uploaded_images or []
    source_chunks = source_chunks or []
    data_preview = data_preview or []
    report_headers = report_headers or []

    # Build all custom styles once and reuse across story sections.
    styles = getSampleStyleSheet()
    title_style = _get_or_add_style(
        styles,
        "TitleX",
        parent=styles["Title"],
        fontName=str(theme["font_name"]),
        fontSize=float(theme["title_size"]),
        leading=float(theme["title_leading"]),
        spaceAfter=12,
        textColor=colors.HexColor(str(theme["heading_color"])),
    )
    h_style = _get_or_add_style(
        styles,
        "HeaderX",
        parent=styles["Heading2"],
        fontName=str(theme["font_name"]),
        fontSize=float(theme["heading_size"]),
        leading=float(theme["heading_leading"]),
        spaceBefore=12,
        spaceAfter=6,
        textColor=colors.HexColor(str(theme["heading_color"])),
    )
    body_style = _get_or_add_style(
        styles,
        "BodyX",
        parent=styles["Normal"],
        fontName=str(theme["font_name"]),
        fontSize=float(theme["body_size"]),
        leading=float(theme["body_leading"]),
        spaceAfter=6,
    )
    cap_style = _get_or_add_style(
        styles,
        "CaptionX",
        parent=styles["Normal"],
        fontName=str(theme["font_name"]),
        fontSize=float(theme["caption_size"]),
        leading=float(theme["caption_leading"]),
        textColor=colors.HexColor(str(theme["caption_color"])),
        spaceAfter=6,
    )

    def _draw_footer(canvas, doc):
        # Footer also sets document metadata (title/author/subject) for exported PDF files.
        canvas.saveState()
        canvas.setTitle(_safe_text(meta.get("title", "Report")))
        author = _safe_text(meta.get("name", ""))
        if author:
            canvas.setAuthor(author)
        subject = _safe_text(meta.get("template", ""))
        if subject:
            canvas.setSubject(subject)
        canvas.setFont(str(theme["font_name"]), footer_font_size)
        canvas.setFillColor(colors.HexColor("#64748b"))
        page_width = float(getattr(doc, "pagesize", letter)[0])
        canvas.drawRightString(page_width - float(layout.get("right_margin", 54)), 24, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    # Create document with merged margins and letter page size.
    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        rightMargin=float(layout.get("right_margin", 54)),
        leftMargin=float(layout.get("left_margin", 54)),
        topMargin=float(layout.get("top_margin", 54)),
        bottomMargin=float(layout.get("bottom_margin", 54)),
    )
    story = []

    # Cover page: title + structured metadata table.
    story.append(Paragraph(_safe_text(meta.get("title", "Report")), title_style))
    cover_rows = [
        ["Template", _safe_text(meta.get("template", ""))],
        ["Name", _safe_text(meta.get("name", ""))],
        ["Course", _safe_text(meta.get("course", ""))],
        ["Group", _safe_text(meta.get("group", ""))],
        ["Date", _safe_text(meta.get("date", ""))],
    ]
    cover_table = Table(cover_rows, colWidths=[1.3 * inch, 4.9 * inch])
    table_grid = colors.HexColor(str(theme["table_grid"]))
    font_name = str(theme["font_name"])
    cover_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.8, table_grid),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, table_grid),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(Spacer(1, 12))
    story.append(cover_table)
    story.append(PageBreak())

    # Source summary page: preserves manual/instruction context for traceability.
    story.append(Paragraph("Source / Instructions Summary", h_style))
    story.extend(_lines_to_paragraphs(source_summary, body_style))

    # Data preview page (optional): first rows for quick dataset sanity check.
    if data_preview:
        story.append(Paragraph("Data Preview (first rows)", h_style))
        cols = list(data_preview[0].keys())
        table_data = [cols]
        for row in data_preview[:max(1, data_preview_rows)]:
            table_data.append([str(row.get(c, "")) for c in cols])

        t = _build_table(table_data, header=True, theme=theme)
        story.append(t)

    story.append(PageBreak())

    # Report section: render by template headers when available, else as raw body.
    story.append(Paragraph("Report", h_style))
    section_images, extra_images = _group_images_by_section(uploaded_images, report_headers)
    figure_index = 1
    rendered_sections = False
    if report_headers:
        sections = split_by_headers(report_text, report_headers)
        for header in report_headers:
            body = _safe_text(sections.get(header, ""))
            assets = section_images.get(header, []) or []
            if not body and not assets:
                continue
            rendered_sections = True
            story.append(Paragraph(header, h_style))
            if body:
                _append_report_text(story, body, h_style, body_style, theme=theme)
            else:
                story.append(Paragraph("—", body_style))
                story.append(Spacer(1, 4))
            for asset in assets:
                if _append_uploaded_image_block(
                    story,
                    asset,
                    figure_index=figure_index,
                    body_style=body_style,
                    cap_style=cap_style,
                    max_width=image_max_width,
                    max_height=image_max_height,
                ):
                    figure_index += 1

    if not rendered_sections:
        _append_report_text(story, report_text, h_style, body_style, theme=theme)
        extra_images = uploaded_images

    # Reviewer feedback page (optional).
    if _safe_text(review_text):
        story.append(PageBreak())
        story.append(Paragraph("Reviewer Feedback", h_style))
        story.extend(_lines_to_paragraphs(review_text, body_style))

    # Generated plot figures (optional).
    if plot_paths:
        story.append(PageBreak())
        story.append(Paragraph("Figures", h_style))
        for title, p in plot_paths.items():
            path = Path(p)
            if not path.exists():
                continue
            story.append(Paragraph(f"Figure {figure_index}. {title}", body_style))
            img = Image(str(path))
            img.drawWidth = plot_width
            img.drawHeight = plot_height
            story.append(img)
            story.append(Paragraph(_figure_note(title), cap_style))
            story.append(Spacer(1, 12))
            figure_index += 1

    # Any images not assigned to a specific report section are appended at the end.
    if extra_images:
        story.append(PageBreak())
        story.append(Paragraph("Uploaded Images", h_style))
        for asset in extra_images:
            if _append_uploaded_image_block(
                story,
                asset,
                figure_index=figure_index,
                body_style=body_style,
                cap_style=cap_style,
                max_width=image_max_width,
                max_height=image_max_height,
            ):
                figure_index += 1

    # Source appendix (optional) maps [S#] citations in report/review to source chunk snippets.
    if include_source_appendix and source_chunks:
        cited_ids = extract_source_tags(f"{report_text}\n{review_text}")
        if cited_ids:
            source_map: dict[str, str] = {}
            for chunk in source_chunks:
                if not isinstance(chunk, dict):
                    continue
                sid = str(chunk.get("id", "")).strip()
                txt = str(chunk.get("text", "")).strip()
                if sid and txt and sid not in source_map:
                    source_map[sid] = txt

            entries = []
            for sid in cited_ids:
                txt = source_map.get(sid, "")
                if not txt:
                    continue
                snippet = " ".join(txt.split())
                if len(snippet) > 560:
                    snippet = snippet[:560].rstrip() + "..."
                entries.append((sid, snippet))

            if entries:
                story.append(PageBreak())
                story.append(Paragraph("Source Traceability", h_style))
                story.append(
                    Paragraph(
                        "Report source tags map to the following manual excerpts.",
                        cap_style,
                    )
                )
                for sid, snippet in entries:
                    story.append(Paragraph(f"[{sid}] {_escape_para_text(snippet)}", body_style))
                    story.append(Spacer(1, 4))

    # Build final PDF and attach consistent footer/metadata on all pages.
    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return out_path
