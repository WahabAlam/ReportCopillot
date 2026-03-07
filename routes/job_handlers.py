"""Route handler helpers for job handlers."""

from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi.responses import FileResponse


def get_draft_payload(
    *,
    job_id: str,
    is_safe_job_id_fn,
    job_dir_fn,
    read_state_fn,
    read_job_debug_fn,
    load_template_cfg_for_job_fn,
    read_job_text_fn,
    write_job_text_fn,
    split_by_headers_fn,
) -> dict:
    # Drafts are editable snapshots for completed/failed/canceled jobs.
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state_fn(job_dir_fn(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")

    dbg = read_job_debug_fn(job_id)
    template_key, template_cfg = load_template_cfg_for_job_fn(job_id, dbg)
    report_text = read_job_text_fn(job_id, "report.txt")
    if not report_text.strip():
        # Fallback for jobs where report.txt was not persisted.
        report_text = (
            (((dbg.get("agent_status") or {}).get("writer") or {}).get("payload") or {}).get("report_text", "")
            or dbg.get("report", "")
            or ""
        )
        if report_text.strip():
            write_job_text_fn(job_id, "report.txt", report_text)
    headers = template_cfg.get("writer_format", []) or []
    sections = split_by_headers_fn(report_text, headers) if headers else {}
    return {
        "job_id": job_id,
        "template": template_key,
        "headers": headers,
        "report_text": report_text,
        "sections": sections,
        "status": st.status,
        "editable": st.status in ("done", "failed", "canceled"),
    }


def save_draft_payload(
    *,
    job_id: str,
    body: dict,
    is_safe_job_id_fn,
    job_dir_fn,
    read_state_fn,
    read_job_debug_fn,
    load_template_cfg_for_job_fn,
    split_by_headers_fn,
    write_job_text_fn,
    upsert_job_debug_fn,
) -> dict:
    # Persist edited report text and pre-split sections for downstream operations.
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state_fn(job_dir_fn(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("done", "failed", "canceled"):
        raise HTTPException(status_code=400, detail="Draft editing is allowed only after job completion or failure.")

    report_text = str((body or {}).get("report_text", "")).strip()
    if not report_text:
        raise HTTPException(status_code=400, detail="Draft report text cannot be empty.")

    dbg = read_job_debug_fn(job_id)
    _, template_cfg = load_template_cfg_for_job_fn(job_id, dbg)
    headers = template_cfg.get("writer_format", []) or []
    sections = split_by_headers_fn(report_text, headers) if headers else {}

    write_job_text_fn(job_id, "report.txt", report_text)
    upsert_job_debug_fn(job_id, {"report_sections": sections})
    return {"ok": True, "job_id": job_id, "saved": True}


def rebuild_job_pdf_payload(
    *,
    job_id: str,
    is_safe_job_id_fn,
    job_dir_fn,
    read_state_fn,
    read_job_debug_fn,
    load_template_cfg_for_job_fn,
    rebuild_pdf_for_job_fn,
) -> dict:
    # Rebuild uses currently persisted text artifacts and metadata.
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state_fn(job_dir_fn(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("done", "failed", "canceled"):
        raise HTTPException(status_code=400, detail="PDF rebuild is allowed only after job completion or failure.")

    dbg = read_job_debug_fn(job_id)
    _, template_cfg = load_template_cfg_for_job_fn(job_id, dbg)
    rebuild_pdf_for_job_fn(job_id, dbg, template_cfg)
    return {"ok": True, "job_id": job_id, "download_url": f"/download/{job_id}"}


def quality_fix_job_payload(
    *,
    job_id: str,
    is_safe_job_id_fn,
    job_dir_fn,
    read_state_fn,
    read_job_debug_fn,
    load_template_cfg_for_job_fn,
    apply_quality_fix_for_job_fn,
) -> dict:
    # Quality fix delegates to service layer and returns a compact summary.
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state_fn(job_dir_fn(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("done", "failed", "canceled"):
        raise HTTPException(status_code=400, detail="Quality fix is allowed only after job completion or failure.")

    dbg = read_job_debug_fn(job_id)
    _, template_cfg = load_template_cfg_for_job_fn(job_id, dbg)
    quality = apply_quality_fix_for_job_fn(job_id, dbg, template_cfg)
    return {
        "ok": True,
        "job_id": job_id,
        "quality_ok": bool(quality.get("ok")),
        "quality_issue_count": len(quality.get("issues", []) or []),
        "download_url": f"/download/{job_id}",
    }


def regenerate_section_payload(
    *,
    job_id: str,
    body: dict,
    is_safe_job_id_fn,
    job_dir_fn,
    read_state_fn,
    read_job_debug_fn,
    load_template_cfg_for_job_fn,
    read_job_text_fn,
    split_by_headers_fn,
    chat_fn,
    write_job_text_fn,
    upsert_job_debug_fn,
    join_sections_fn,
    rebuild_pdf_for_job_fn,
) -> dict:
    # Section regeneration is a targeted edit pass over one report section.
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state_fn(job_dir_fn(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("done", "failed", "canceled"):
        raise HTTPException(status_code=400, detail="Section regeneration is allowed only after job completion or failure.")

    dbg = read_job_debug_fn(job_id)
    template_key, template_cfg = load_template_cfg_for_job_fn(job_id, dbg)
    headers = template_cfg.get("writer_format", []) or []
    target = str((body or {}).get("section", "")).strip()
    if not target:
        raise HTTPException(status_code=400, detail="Section is required.")
    if headers and target not in headers:
        raise HTTPException(status_code=400, detail=f"Unknown section '{target}' for template '{template_key}'.")

    report_text = read_job_text_fn(job_id, "report.txt")
    if not report_text.strip():
        raise HTTPException(status_code=400, detail="No report draft available for regeneration.")
    sections = split_by_headers_fn(report_text, headers) if headers else {}
    if headers and target not in sections:
        raise HTTPException(status_code=400, detail=f"Section '{target}' not found in report draft.")

    theory_text = read_job_text_fn(job_id, "theory.txt")
    current_section = sections.get(target, "") if headers else ""
    extra = str((body or {}).get("instructions", "")).strip()
    data_summary = (((dbg.get("agent_status") or {}).get("data") or {}).get("payload") or {}).get("data_summary", {})
    image_assets = ((dbg.get("request_payload") or {}).get("image_assets") or [])

    system = (
        "You revise exactly one report section.\n"
        "Rules:\n"
        "- Return only the rewritten section body text (no section header).\n"
        "- Preserve factual consistency with theory/data.\n"
        "- Do not invent measurements.\n"
        "- Keep it detailed, clear, and submission-ready.\n"
    )
    user = f"""TEMPLATE: {template_cfg.get("display_name", template_key)}
TARGET SECTION: {target}

CURRENT SECTION BODY:
{current_section}

THEORY:
{theory_text}

DATA SUMMARY (JSON):
{json.dumps(data_summary, indent=2)}

UPLOADED IMAGE CONTEXT (JSON):
{json.dumps(image_assets, indent=2)}

ADDITIONAL INSTRUCTIONS:
{extra or "(none)"}
"""
    new_body = (chat_fn(system, user) or "").strip()
    if not new_body:
        raise HTTPException(status_code=500, detail="Model returned empty section content.")

    if headers:
        sections[target] = new_body
        new_report = join_sections_fn(sections, headers)
    else:
        new_report = report_text

    write_job_text_fn(job_id, "report.txt", new_report)
    upsert_job_debug_fn(job_id, {"report_sections": sections})
    rebuild_pdf_for_job_fn(job_id, dbg, template_cfg)
    return {"ok": True, "job_id": job_id, "section": target, "download_url": f"/download/{job_id}"}


def job_page_response(
    *,
    request,
    job_id: str,
    templates_engine,
    is_safe_job_id_fn,
    read_state_fn,
    job_dir_fn,
):
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    st = read_state_fn(job_dir_fn(job_id))
    if not st:
        # Render friendly "not found".
        return templates_engine.TemplateResponse(
            "job.html",
            {"request": request, "job_id": job_id, "state": None},
            status_code=404,
        )

    return templates_engine.TemplateResponse(
        "job.html",
        {"request": request, "job_id": job_id, "state": st.__dict__},
    )


def job_status_payload(
    *,
    job_id: str,
    is_safe_job_id_fn,
    read_state_fn,
    job_dir_fn,
) -> dict:
    # Status endpoint merges volatile state.json and optional debug diagnostics.
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    st = read_state_fn(job_dir_fn(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")

    payload = dict(st.__dict__)
    debug_path = job_dir_fn(job_id) / "debug.json"
    if debug_path.exists():
        try:
            dbg = json.loads(debug_path.read_text(encoding="utf-8"))
            payload["timings_ms"] = ((dbg.get("agent_status") or {}).get("timings_ms") or {})
            payload["pipeline_duration_ms"] = dbg.get("pipeline_duration_ms")
            payload["quality_ok"] = ((dbg.get("quality") or {}).get("ok"))
            issues = ((dbg.get("quality") or {}).get("issues") or [])
            payload["quality_issue_count"] = len(issues)
            payload["quality_issues"] = issues[:10]
        except Exception:
            payload["timings_ms"] = {}
    return payload


def cancel_job_payload(
    *,
    job_id: str,
    x_admin_key: str | None,
    require_admin_key_fn,
    is_safe_job_id_fn,
    job_dir_fn,
    read_state_fn,
    write_state_fn,
    log_event_fn,
) -> dict:
    # Cancellation is cooperative: mark requested and let worker stop safely.
    require_admin_key_fn(x_admin_key)
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    jdir = job_dir_fn(job_id)
    st = read_state_fn(jdir)
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")

    if st.status in ("done", "failed", "canceled"):
        return {"job_id": job_id, "status": st.status, "message": "Job is already finished."}

    st.cancellation_requested = True
    st.stage = "cancel_requested"
    write_state_fn(jdir, st)
    log_event_fn("job_cancel_requested", job_id=job_id, status=st.status)
    return {"job_id": job_id, "status": st.status, "message": "Cancellation requested."}


def cleanup_payload(
    *,
    max_age_hours: int,
    dry_run: bool,
    x_admin_key: str | None,
    require_admin_key_fn,
    cleanup_artifacts_fn,
) -> dict:
    # Cleanup stays admin-gated because it may delete artifacts.
    require_admin_key_fn(x_admin_key)
    return cleanup_artifacts_fn(max_age_hours=max_age_hours, dry_run=dry_run)


def download_response(
    *,
    job_id: str,
    is_safe_job_id_fn,
    job_pdf_path_fn,
):
    # Serve generated PDF directly once it exists on disk.
    if not is_safe_job_id_fn(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    pdf = job_pdf_path_fn(job_id)
    if not pdf.exists():
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(
        str(pdf),
        media_type="application/pdf",
        filename=f"{job_id}.pdf",
    )
