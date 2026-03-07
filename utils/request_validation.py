"""Utility helpers for request validation."""

from __future__ import annotations

from pathlib import Path
from fastapi import HTTPException, UploadFile

from utils.files import save_upload
from utils.lab_data import read_tabular_file, save_table_text_as_csv


def validate_csv(csv_path: str) -> dict:
    try:
        df = read_tabular_file(csv_path)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not read tabular data file. Supported formats: CSV, TSV, Excel (.xlsx/.xls), JSON. "
                f"Details: {type(e).__name__}: {e}"
            ),
        )

    if df.shape[0] < 2:
        raise HTTPException(status_code=400, detail="CSV must have at least 2 rows of data.")

    numeric_cols = list(df.select_dtypes(include="number").columns)
    if not numeric_cols:
        raise HTTPException(status_code=400, detail="CSV must contain at least one numeric column.")

    return {
        "rows": int(df.shape[0]),
        "cols": int(df.shape[1]),
        "columns": list(df.columns),
        "numeric_columns": numeric_cols,
        "preview_head": df.head(5).to_dict(orient="records"),
    }


def save_table_text_data(table_text: str) -> str:
    text = (table_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Table text input is empty.")
    try:
        return save_table_text_as_csv(text)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse table text. Expected CSV/TSV/markdown-style table. Details: {type(e).__name__}: {e}",
        )


def guess_image_sections(filename: str, template_key: str) -> list[str]:
    name = (filename or "").lower()
    sections: list[str] = []

    if any(k in name for k in ("setup", "apparatus", "equipment", "procedure", "method")):
        sections.append("Apparatus & Procedure" if template_key == "lab_report" else "Methods")
    if any(k in name for k in ("result", "measurement", "output", "graph", "plot", "curve")):
        sections.append("Results" if template_key == "lab_report" else "Key Insights")
    if any(k in name for k in ("error", "issue", "outlier", "limitation", "anomaly")):
        sections.append("Discussion" if template_key == "lab_report" else "Risks & Limitations")

    if not sections:
        sections.append("Results" if template_key == "lab_report" else "Key Insights")
    return sections[:3]


def save_image_uploads(
    image_files: list[UploadFile],
    template_key: str,
    *,
    template_cfg: dict,
    image_titles: list[str] | None = None,
    image_captions: list[str] | None = None,
    image_sections: list[str] | None = None,
    max_image_uploads: int,
    image_extensions: set[str],
) -> list[dict]:
    clean = [
        f for f in (image_files or [])
        if f is not None and getattr(f, "filename", None) and str(f.filename).strip() != ""
    ]
    if not clean:
        return []
    if len(clean) > max_image_uploads:
        raise HTTPException(status_code=400, detail=f"Too many images uploaded (max {max_image_uploads}).")

    image_titles = image_titles or []
    image_captions = image_captions or []
    image_sections = image_sections or []
    valid_sections = set(template_cfg.get("writer_format", []) or [])

    assets: list[dict] = []
    for i, f in enumerate(clean, start=1):
        try:
            path = save_upload(f, allowed_extensions=image_extensions)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        filename = Path(getattr(f, "filename", "")).name
        title = (image_titles[i - 1] if i - 1 < len(image_titles) else "").strip()[:120]
        caption = (image_captions[i - 1] if i - 1 < len(image_captions) else "").strip()[:1000]
        target_section = (image_sections[i - 1] if i - 1 < len(image_sections) else "").strip()
        if target_section and target_section not in valid_sections:
            target_section = ""
        suggested_sections = [target_section] if target_section else guess_image_sections(filename, template_key)
        assets.append(
            {
                "label": f"Image {i}",
                "filename": filename,
                "path": path,
                "title": title,
                "caption": caption,
                "target_section": target_section,
                "suggested_sections": suggested_sections,
            }
        )
    return assets


def validate_text_lengths(
    *,
    report_title: str,
    student_name: str,
    course: str,
    group: str,
    date: str,
    goal: str,
    extra_instructions: str,
    lab_format_description: str,
    layout_preferences: str,
    final_manual_text: str,
) -> None:
    limits = {
        "report_title": (report_title, 200),
        "student_name": (student_name, 120),
        "course": (course, 120),
        "group": (group, 120),
        "date": (date, 120),
        "goal": (goal, 3000),
        "extra_instructions": (extra_instructions, 5000),
        "lab_format_description": (lab_format_description, 2500),
        "layout_preferences": (layout_preferences, 2500),
        "manual_text": (final_manual_text, 400000),
    }
    for field, (value, max_len) in limits.items():
        if len((value or "").strip()) > max_len:
            raise HTTPException(status_code=400, detail=f"Field '{field}' is too long (max {max_len} chars).")


def validate_template_inputs(
    *,
    template_key: str,
    template_cfg: dict,
    has_csv: bool,
    has_images: bool,
    include_review_bool: bool,
    goal: str,
) -> None:
    schema = template_cfg.get("form_schema", {}) or {}
    allow_csv = bool(schema.get("allow_csv", True))
    require_csv = bool(schema.get("require_csv", template_cfg.get("needs_csv", False)))
    allow_review = bool(schema.get("allow_review", template_cfg.get("include_review", False)))
    allow_images = bool(schema.get("allow_images", False))
    require_any_of = [str(v).strip().lower() for v in (schema.get("require_any_of") or []) if str(v).strip()]
    goal_min_len = int(schema.get("goal_min_len", 0))

    if require_csv and not has_csv:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' requires tabular data input.")
    if not allow_csv and has_csv:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' does not accept tabular data input.")
    if not allow_images and has_images:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' does not accept image uploads.")
    if include_review_bool and not allow_review:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' does not support reviewer feedback.")

    if require_any_of:
        source_flags = {
            "csv": bool(has_csv),
            "images": bool(has_images),
        }
        if not any(source_flags.get(src, False) for src in require_any_of):
            readable = " or ".join([src.upper() if src == "csv" else src for src in require_any_of])
            raise HTTPException(
                status_code=400,
                detail=f"Template '{template_key}' requires at least one data source: {readable}.",
            )

    if len((goal or "").strip()) < goal_min_len:
        raise HTTPException(
            status_code=400,
            detail=f"Template '{template_key}' requires goal length >= {goal_min_len} characters.",
        )
