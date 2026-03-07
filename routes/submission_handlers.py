"""Route handler helpers for submission handlers."""

from __future__ import annotations

import os
import re

from fastapi import HTTPException


_LAYOUT_HEADER_RE = re.compile(r"^[A-Za-z0-9 &/()\-]{2,64}$")


def _extract_layout_section_headers(layout_preferences: str, *, max_sections: int = 14) -> list[str]:
    text = (layout_preferences or "").strip()
    if not text:
        return []

    candidates: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^\d+[\).\-\s]+", "", line).strip()
        line = re.sub(r"^[-*•]\s+", "", line).strip()
        if not line:
            continue

        lowered = line.lower()
        if ":" in line and lowered.startswith(("sections:", "section order:", "order:", "layout:")):
            line = line.split(":", 1)[1].strip()

        if any(sep in line for sep in ("->", "→", "|", ">")):
            parts = re.split(r"\s*(?:->|→|\||>)\s*", line)
        elif "," in line:
            parts = [p.strip() for p in line.split(",")]
        elif line.endswith(":"):
            parts = [line[:-1].strip()]
        else:
            parts = [line]

        for part in parts:
            section = part.strip().strip(":").strip()
            if not section:
                continue
            if len(section.split()) > 8:
                continue
            if not _LAYOUT_HEADER_RE.fullmatch(section):
                continue
            candidates.append(section)

    out: list[str] = []
    seen: set[str] = set()
    for section in candidates:
        key = section.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(section)
        if len(out) >= max_sections:
            break

    # Require a meaningful structure list; avoid treating one-off prose lines as full layout overrides.
    if len(out) < 3:
        return []
    return out


def _merge_generation_preferences(
    *,
    extra_instructions: str,
    lab_format_description: str,
    layout_preferences: str,
) -> str:
    parts: list[str] = []
    base = (extra_instructions or "").strip()
    if base:
        parts.append(base)
    lab_fmt = (lab_format_description or "").strip()
    if lab_fmt:
        parts.append("Lab Format Description:\n" + lab_fmt)
    layout = (layout_preferences or "").strip()
    if layout:
        parts.append("Preferred Output Layout:\n" + layout)
    return "\n\n".join(parts).strip()


async def run_payload(
    *,
    request,
    background_tasks,
    template: str,
    manual_text: str,
    manual_pdf,
    report_title: str,
    student_name: str,
    course: str,
    group: str,
    date: str,
    goal: str,
    lab_format_description: str,
    layout_preferences: str,
    extra_instructions: str,
    print_profile: str,
    data_csv,
    data_table_text: str,
    lab_images,
    lab_image_titles,
    lab_image_captions,
    lab_image_sections,
    include_review: str,
    check_rate_limit_fn,
    get_template_fn,
    normalize_print_profile_fn,
    save_upload_fn,
    save_table_text_fn,
    pdf_to_text_fn,
    validate_template_inputs_fn,
    validate_csv_fn,
    save_image_uploads_fn,
    validate_text_lengths_fn,
    queue_pipeline_job_fn,
    build_job_summary_fn,
    max_image_uploads: int,
    image_extensions: set[str],
    tabular_data_extensions: set[str],
) -> dict:
    # Throttle early before touching disk/LLM resources.
    check_rate_limit_fn(request)

    try:
        template_cfg = get_template_fn(template)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown template: {template}")

    include_review_bool = (include_review == "1")
    print_profile = normalize_print_profile_fn(print_profile, strict=True)

    # Manual source can come from raw text or uploaded PDF extraction.
    extracted_manual_text = ""
    has_manual_pdf = (
        manual_pdf is not None
        and getattr(manual_pdf, "filename", None)
        and manual_pdf.filename.strip() != ""
    )
    if has_manual_pdf:
        try:
            pdf_path = save_upload_fn(manual_pdf, allowed_extensions={".pdf"})
            pdf_max_pages = int(os.getenv("PDF_MAX_PAGES", "0"))
            extracted_manual_text = pdf_to_text_fn(pdf_path, max_pages=pdf_max_pages if pdf_max_pages > 0 else None)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception:
            raise HTTPException(status_code=400, detail="Failed to read manual PDF. Try manual_text instead.")

        if not extracted_manual_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from manual PDF (might be scanned). Paste manual_text instead.",
            )

    final_manual_text = extracted_manual_text.strip() if extracted_manual_text.strip() else manual_text.strip()
    if not final_manual_text:
        raise HTTPException(status_code=400, detail="Provide either manual_pdf (preferred) or manual_text.")

    # CSV and image assets are optional and template-dependent.
    csv_path = None
    csv_info = {"rows": 0, "cols": 0, "columns": [], "numeric_columns": [], "preview_head": []}
    has_uploaded_data_file = (
        data_csv is not None
        and getattr(data_csv, "filename", None)
        and data_csv.filename.strip() != ""
    )
    has_table_data_text = bool((data_table_text or "").strip())
    image_uploads = [
        upload for upload in (lab_images or [])
        if upload is not None and getattr(upload, "filename", None) and str(upload.filename).strip() != ""
    ]
    has_images = bool(image_uploads)

    validate_template_inputs_fn(
        template_key=template,
        template_cfg=template_cfg,
        has_csv=bool(has_uploaded_data_file or has_table_data_text),
        has_images=bool(has_images),
        include_review_bool=include_review_bool,
        goal=goal,
    )

    if has_uploaded_data_file:
        try:
            csv_path = save_upload_fn(data_csv, allowed_extensions=tabular_data_extensions)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        csv_info = validate_csv_fn(csv_path)
    elif has_table_data_text:
        csv_path = save_table_text_fn(data_table_text)
        csv_info = validate_csv_fn(csv_path)

    image_assets = save_image_uploads_fn(
        image_uploads,
        template,
        template_cfg=template_cfg,
        image_titles=lab_image_titles,
        image_captions=lab_image_captions,
        image_sections=lab_image_sections,
        max_image_uploads=max_image_uploads,
        image_extensions=image_extensions,
    )

    merged_extra_instructions = _merge_generation_preferences(
        extra_instructions=extra_instructions,
        lab_format_description=lab_format_description,
        layout_preferences=layout_preferences,
    )
    layout_section_headers = _extract_layout_section_headers(layout_preferences)
    if layout_section_headers:
        merged_extra_instructions = (
            merged_extra_instructions
            + "\n\nUser-defined section layout (highest priority):\n"
            + "\n".join([f"- {h}" for h in layout_section_headers])
        ).strip()

    validate_text_lengths_fn(
        report_title=report_title,
        student_name=student_name,
        course=course,
        group=group,
        date=date,
        goal=goal,
        extra_instructions=extra_instructions,
        lab_format_description=lab_format_description,
        layout_preferences=layout_preferences,
        final_manual_text=final_manual_text,
    )

    final_title = report_title.strip() or template_cfg.get("pdf_title_default", "Report")
    meta = {
        "title": final_title,
        "template": template_cfg.get("display_name", template),
        "name": student_name,
        "course": course,
        "group": group,
        "date": date,
    }

    # Persisted payload must be self-contained so retry can reuse it later.
    request_payload = {
        "template": template,
        "manual_text": final_manual_text,
        "goal": goal,
        "csv_path": csv_path,
        "image_assets": image_assets,
        "extra_instructions": merged_extra_instructions,
        "lab_format_description": lab_format_description,
        "layout_preferences": layout_preferences,
        "layout_section_headers": layout_section_headers,
        "print_profile": print_profile,
        "include_review_bool": include_review_bool,
        "csv_info": csv_info,
        "meta": meta,
    }
    job_id, queue_res, _ = queue_pipeline_job_fn(
        background_tasks=background_tasks,
        payload=request_payload,
    )

    return {
        "job_id": job_id,
        "job_url": f"/job/{job_id}",
        "download_url": f"/download/{job_id}",
        "status_url": f"/status/{job_id}",
        "template": template,
        "status": "queued",
        "stage": "queued",
        "progress_pct": 0,
        "queue_mode": queue_res["mode"],
        "queue_job_id": queue_res["job_id"],
        "summary": build_job_summary_fn(template_cfg=template_cfg, payload=request_payload),
    }


async def retry_payload(
    *,
    job_id: str,
    background_tasks,
    is_safe_job_id_fn,
    read_state_fn,
    job_dir_fn,
    read_job_debug_fn,
    queue_pipeline_job_fn,
    build_job_summary_fn,
) -> dict:
    # Retry replays the original request payload into a fresh job id.
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state_fn(job_dir_fn(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("failed", "canceled"):
        raise HTTPException(status_code=400, detail="Only failed/canceled jobs can be retried.")

    dbg = read_job_debug_fn(job_id)
    payload = dbg.get("request_payload") if isinstance(dbg, dict) else None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Retry data unavailable for this job.")

    for key in ("template", "manual_text", "goal", "extra_instructions", "csv_info", "meta"):
        if key not in payload:
            raise HTTPException(status_code=400, detail=f"Retry payload missing required key: {key}")

    new_job_id_value, queue_res, template_cfg = queue_pipeline_job_fn(
        background_tasks=background_tasks,
        payload=payload,
        retry_of=job_id,
    )

    return {
        "job_id": new_job_id_value,
        "retry_of": job_id,
        "job_url": f"/job/{new_job_id_value}",
        "download_url": f"/download/{new_job_id_value}",
        "status_url": f"/status/{new_job_id_value}",
        "template": payload["template"],
        "status": "queued",
        "stage": "queued",
        "progress_pct": 0,
        "queue_mode": queue_res["mode"],
        "queue_job_id": queue_res["job_id"],
        "summary": build_job_summary_fn(template_cfg=template_cfg, payload=payload),
    }
