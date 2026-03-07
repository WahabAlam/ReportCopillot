"""Service-layer logic for job pdf."""

from __future__ import annotations

import os

from fastapi import HTTPException

from agents.writer_agent import run as writer_run
from templates import (
    get_template,
    DEFAULT_TEMPLATE,
    TEMPLATES,
    resolve_template_cfg,
    apply_layout_section_headers,
)
from utils.jobs import (
    job_pdf_path,
    read_job_debug,
    read_job_text,
    upsert_job_debug,
    write_job_text,
)
from utils.pdf_report import build_submission_pdf
from utils.plots import generate_plots
from utils.quality_gate import (
    evaluate_report_quality,
    build_quality_fix_prompt,
    select_quality_fix_sections,
)
from utils.retrieval import build_source_chunks
from utils.sections import split_by_headers


def load_template_cfg_for_job(job_id: str, dbg: dict) -> tuple[str, dict]:
    # Prefer explicit template from debug payload; fallback to header-based inference for legacy jobs.
    req = dbg.get("request_payload") if isinstance(dbg, dict) else {}
    req = req if isinstance(req, dict) else {}
    has_csv = bool(req.get("csv_path")) or bool(dbg.get("has_csv"))

    template_key = (dbg.get("template") or "").strip()
    if template_key:
        try:
            cfg = resolve_template_cfg(get_template(template_key), has_csv=has_csv)
            cfg = apply_layout_section_headers(cfg, req.get("layout_section_headers") or [])
            return template_key, cfg
        except KeyError:
            pass

    # Fallback for legacy/debug-incomplete jobs: infer from report headers.
    report_text = read_job_text(job_id, "report.txt")
    best_key = DEFAULT_TEMPLATE
    best_score = -1
    for key, cfg in TEMPLATES.items():
        headers = cfg.get("writer_format", []) or []
        if not headers:
            continue
        score = 0
        for h in headers:
            if f"{h}:" in report_text:
                score += 1
        if score > best_score:
            best_score = score
            best_key = key
    cfg = resolve_template_cfg(get_template(best_key), has_csv=has_csv)
    cfg = apply_layout_section_headers(cfg, req.get("layout_section_headers") or [])
    return best_key, cfg


def rebuild_pdf_for_job(
    job_id: str,
    dbg: dict,
    template_cfg: dict,
    *,
    normalize_print_profile_fn,
) -> None:
    # Rebuild reads persisted artifacts so edits can be reflected without rerunning agents.
    req = dbg.get("request_payload") if isinstance(dbg, dict) else {}
    req = req if isinstance(req, dict) else {}

    report_text = read_job_text(job_id, "report.txt")
    theory_text = read_job_text(job_id, "theory.txt")
    review_text = read_job_text(job_id, "review.txt")
    csv_info = req.get("csv_info") or {}
    csv_path = req.get("csv_path")
    image_assets = req.get("image_assets") or []
    source_chunks = build_source_chunks(str(req.get("manual_text", "") or ""))
    print_profile = normalize_print_profile_fn(req.get("print_profile"), strict=False)
    include_review_bool = bool(req.get("include_review_bool", False))

    if not (include_review_bool and template_cfg.get("include_review", False)):
        review_text = ""

    plot_paths = {}
    if template_cfg.get("include_plots", False) and csv_path and os.path.exists(csv_path):
        plot_paths = generate_plots(csv_path, job_id=job_id)

    meta = dbg.get("meta") if isinstance(dbg, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    if not meta:
        meta = {
            "title": template_cfg.get("pdf_title_default", "Report"),
            "template": template_cfg.get("display_name", req.get("template", "")),
            "name": "",
            "course": "",
            "group": "",
            "date": "",
        }

    build_submission_pdf(
        out_path=str(job_pdf_path(job_id)),
        meta=meta,
        source_summary=theory_text,
        report_text=report_text,
        review_text=review_text,
        data_preview=csv_info.get("preview_head", []),
        plot_paths=plot_paths,
        uploaded_images=image_assets,
        source_chunks=source_chunks,
        include_source_appendix=bool(template_cfg.get("include_source_appendix", True)),
        theme=template_cfg.get("pdf_theme", {}),
        report_headers=template_cfg.get("writer_format", []),
        print_profile=print_profile,
    )


def apply_quality_fix_for_job(
    job_id: str,
    dbg: dict,
    template_cfg: dict,
    *,
    normalize_print_profile_fn,
    writer_run_fn=writer_run,
) -> dict:
    # Run quality gate and, if needed, trigger one writer repair pass plus PDF rebuild.
    report_text = read_job_text(job_id, "report.txt")
    if not report_text.strip():
        raise HTTPException(status_code=400, detail="No report draft available for quality fix.")

    quality = evaluate_report_quality(report_text, template_cfg)
    if quality.get("ok"):
        return quality

    req = dbg.get("request_payload") if isinstance(dbg, dict) else {}
    req = req if isinstance(req, dict) else {}
    data_summary = (((dbg.get("agent_status") or {}).get("data") or {}).get("payload") or {}).get("data_summary", {})
    data_highlights = (((dbg.get("agent_status") or {}).get("data") or {}).get("payload") or {}).get("data_highlights", {})
    research_facts = (((dbg.get("agent_status") or {}).get("research") or {}).get("payload") or {}).get("research_facts", {})
    image_assets = req.get("image_assets") or []
    source_chunks = build_source_chunks(str(req.get("manual_text", "") or ""))
    theory_text = read_job_text(job_id, "theory.txt")
    fix_prompt = build_quality_fix_prompt(quality.get("issues", []), template_cfg)
    base_extra = str(req.get("extra_instructions", "") or "").strip()
    merged_extra = (base_extra + "\n\n" + fix_prompt).strip()
    required_headers = template_cfg.get("writer_format", []) or []
    existing_sections = split_by_headers(report_text, required_headers) if required_headers else {}
    rewrite_targets = select_quality_fix_sections(quality.get("issues", []), required_headers)

    wr = writer_run_fn(
        job_id=job_id,
        ctx={
            "template_cfg": template_cfg,
            "goal": str(req.get("goal", "") or ""),
            "theory_text": theory_text,
            "research_facts": research_facts,
            "data_summary": data_summary,
            "data_highlights": data_highlights,
            "image_assets": image_assets,
            "source_chunks": source_chunks,
            "extra_instructions": merged_extra,
            "rewrite_targets": rewrite_targets,
            "existing_sections": existing_sections,
            "existing_section_sources": {},
        },
    )
    if not wr.ok:
        msg = wr.error.message if wr.error else "Writer failed"
        detail = wr.error.detail if wr.error else ""
        raise HTTPException(status_code=500, detail=f"Quality fix failed: {msg}: {detail}")

    new_report = wr.payload.get("report_text", "")
    if not new_report.strip():
        raise HTTPException(status_code=500, detail="Quality fix returned empty report.")

    write_job_text(job_id, "report.txt", new_report)
    sections = wr.payload.get("sections", {}) or {}
    quality2 = evaluate_report_quality(new_report, template_cfg)
    upsert_job_debug(
        job_id,
        {
            "report_sections": sections,
            "section_sources": wr.payload.get("section_sources", {}) or {},
            "quality": quality2,
        },
    )
    rebuild_pdf_for_job(
        job_id,
        read_job_debug(job_id),
        template_cfg,
        normalize_print_profile_fn=normalize_print_profile_fn,
    )
    return quality2
