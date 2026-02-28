from __future__ import annotations

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Header, Body
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import pandas as pd
import json
import logging
from time import perf_counter
from time import monotonic
import os
import threading
from collections import defaultdict, deque
from pathlib import Path

from templates import get_template, DEFAULT_TEMPLATE, TEMPLATES
from orchestrator import run_pipeline, CancelledError
from agents.writer_agent import run as writer_run
from utils.files import save_upload
from utils.pdf_text import pdf_to_text
from utils.plots import generate_plots
from utils.pdf_report import build_submission_pdf
from utils.jobs import (
    new_job_id,
    job_pdf_path,
    is_safe_job_id,
    job_dir,
    write_job_debug,
    read_job_debug,
    upsert_job_debug,
    write_job_text,
    read_job_text,
)
from utils.state import new_state, write_state, read_state
from utils.cleanup import cleanup_artifacts
from utils.queue import enqueue_job
from utils.sections import split_by_headers, join_sections
from utils.llm import chat
from utils.quality_gate import evaluate_report_quality, build_quality_fix_prompt

from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles

load_dotenv()
logger = logging.getLogger("report_copilot")
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RUN_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RUN_RATE_LIMIT_MAX_REQUESTS", "20"))
RATE_LIMIT_ENABLED = os.getenv("RUN_RATE_LIMIT_ENABLED", "1") == "1"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()
RATE_LIMIT_BUCKETS: dict[str, deque] = defaultdict(deque)
RATE_LIMIT_LOCK = threading.Lock()
USE_RQ_QUEUE = os.getenv("USE_RQ_QUEUE", "0") == "1"

app = FastAPI(title="Report Copilot (Template-Based)")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/app")
def app_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/template-configs")
def template_configs():
    public = {}
    for key, cfg in TEMPLATES.items():
        schema = cfg.get("form_schema", {}) or {}
        public[key] = {
            "display_name": cfg.get("display_name", key),
            "pdf_title_default": cfg.get("pdf_title_default", "Report"),
            "needs_csv": bool(cfg.get("needs_csv", False)),
            "include_review": bool(cfg.get("include_review", False)),
            "include_plots": bool(cfg.get("include_plots", False)),
            "writer_format": cfg.get("writer_format", []),
            "form_schema": {
                "allow_csv": bool(schema.get("allow_csv", True)),
                "require_csv": bool(schema.get("require_csv", cfg.get("needs_csv", False))),
                "allow_review": bool(schema.get("allow_review", cfg.get("include_review", False))),
                "goal_min_len": int(schema.get("goal_min_len", 0)),
                "goal_placeholder": schema.get("goal_placeholder", ""),
                "manual_placeholder": schema.get("manual_placeholder", ""),
                "extra_placeholder": schema.get("extra_placeholder", ""),
            },
        }
    return {
        "default_template": DEFAULT_TEMPLATE,
        "templates": public,
        "runtime": {
            "admin_protected_endpoints": bool(ADMIN_API_KEY),
            "run_rate_limit_enabled": bool(RATE_LIMIT_ENABLED),
            "run_rate_limit_max_requests": RATE_LIMIT_MAX_REQUESTS,
            "run_rate_limit_window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            "use_rq_queue": bool(USE_RQ_QUEUE),
            "rq_queue_name": os.getenv("RQ_QUEUE_NAME", "report_jobs"),
        },
    }


@app.get("/recent-jobs")
def recent_jobs(limit: int = 10, show_all: bool = False):
    limit = max(1, min(int(limit), 50))
    out = []
    root = Path("outputs")
    if not root.exists():
        return {"jobs": []}

    for d in root.iterdir():
        if not d.is_dir():
            continue
        job_id = d.name
        if not is_safe_job_id(job_id):
            continue
        st = read_state(d)
        if not st:
            continue
        dbg = read_job_debug(job_id)
        template_name = dbg.get("template")
        if not show_all and not template_name:
            # Hide synthetic/system-only entries by default (commonly test artifacts).
            continue
        out.append(
            {
                "job_id": job_id,
                "status": st.status,
                "stage": st.stage,
                "progress_pct": st.progress_pct,
                "updated_at": st.updated_at,
                "created_at": st.created_at,
                "template": template_name,
                "template_display_name": dbg.get("template_display_name"),
                "queue_mode": st.queue_mode,
                "job_url": f"/job/{job_id}",
                "download_url": f"/download/{job_id}",
            }
        )

    out.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return {"jobs": out[:limit]}


def _load_template_cfg_for_job(job_id: str, dbg: dict) -> tuple[str, dict]:
    template_key = (dbg.get("template") or "").strip()
    if template_key:
        try:
            return template_key, get_template(template_key)
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
    return best_key, get_template(best_key)


def _rebuild_pdf_for_job(job_id: str, dbg: dict, template_cfg: dict) -> None:
    req = dbg.get("request_payload") if isinstance(dbg, dict) else {}
    req = req if isinstance(req, dict) else {}

    report_text = read_job_text(job_id, "report.txt")
    theory_text = read_job_text(job_id, "theory.txt")
    review_text = read_job_text(job_id, "review.txt")
    csv_info = req.get("csv_info") or {}
    csv_path = req.get("csv_path")
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
    )


def _apply_quality_fix_for_job(job_id: str, dbg: dict, template_cfg: dict) -> dict:
    report_text = read_job_text(job_id, "report.txt")
    if not report_text.strip():
        raise HTTPException(status_code=400, detail="No report draft available for quality fix.")

    quality = evaluate_report_quality(report_text, template_cfg)
    if quality.get("ok"):
        return quality

    req = dbg.get("request_payload") if isinstance(dbg, dict) else {}
    req = req if isinstance(req, dict) else {}
    data_summary = (((dbg.get("agent_status") or {}).get("data") or {}).get("payload") or {}).get("data_summary", {})
    theory_text = read_job_text(job_id, "theory.txt")
    fix_prompt = build_quality_fix_prompt(quality.get("issues", []), template_cfg)
    base_extra = str(req.get("extra_instructions", "") or "").strip()
    merged_extra = (base_extra + "\n\n" + fix_prompt).strip()

    wr = writer_run(
        job_id=job_id,
        ctx={
            "template_cfg": template_cfg,
            "theory_text": theory_text,
            "data_summary": data_summary,
            "extra_instructions": merged_extra,
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
            "quality": quality2,
        },
    )
    _rebuild_pdf_for_job(job_id, read_job_debug(job_id), template_cfg)
    return quality2


@app.get("/draft/{job_id}")
def get_draft(job_id: str):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state(job_dir(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")

    dbg = read_job_debug(job_id)
    template_key, template_cfg = _load_template_cfg_for_job(job_id, dbg)
    report_text = read_job_text(job_id, "report.txt")
    if not report_text.strip():
        # Fallback for jobs where report.txt was not persisted.
        report_text = (
            (((dbg.get("agent_status") or {}).get("writer") or {}).get("payload") or {}).get("report_text", "")
            or dbg.get("report", "")
            or ""
        )
        if report_text.strip():
            write_job_text(job_id, "report.txt", report_text)
    headers = template_cfg.get("writer_format", []) or []
    sections = split_by_headers(report_text, headers) if headers else {}
    return {
        "job_id": job_id,
        "template": template_key,
        "headers": headers,
        "report_text": report_text,
        "sections": sections,
        "status": st.status,
        "editable": st.status in ("done", "failed", "canceled"),
    }


@app.post("/draft/{job_id}")
def save_draft(job_id: str, body: dict = Body(...)):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state(job_dir(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("done", "failed", "canceled"):
        raise HTTPException(status_code=400, detail="Draft editing is allowed only after job completion or failure.")

    report_text = str((body or {}).get("report_text", "")).strip()
    if not report_text:
        raise HTTPException(status_code=400, detail="Draft report text cannot be empty.")

    dbg = read_job_debug(job_id)
    _, template_cfg = _load_template_cfg_for_job(job_id, dbg)
    headers = template_cfg.get("writer_format", []) or []
    sections = split_by_headers(report_text, headers) if headers else {}

    write_job_text(job_id, "report.txt", report_text)
    upsert_job_debug(job_id, {"report_sections": sections})
    return {"ok": True, "job_id": job_id, "saved": True}


@app.post("/rebuild/{job_id}")
def rebuild_job_pdf(job_id: str):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state(job_dir(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("done", "failed", "canceled"):
        raise HTTPException(status_code=400, detail="PDF rebuild is allowed only after job completion or failure.")

    dbg = read_job_debug(job_id)
    _, template_cfg = _load_template_cfg_for_job(job_id, dbg)
    _rebuild_pdf_for_job(job_id, dbg, template_cfg)
    return {"ok": True, "job_id": job_id, "download_url": f"/download/{job_id}"}


@app.post("/quality-fix/{job_id}")
def quality_fix_job(job_id: str):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state(job_dir(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("done", "failed", "canceled"):
        raise HTTPException(status_code=400, detail="Quality fix is allowed only after job completion or failure.")

    dbg = read_job_debug(job_id)
    _, template_cfg = _load_template_cfg_for_job(job_id, dbg)
    quality = _apply_quality_fix_for_job(job_id, dbg, template_cfg)
    return {
        "ok": True,
        "job_id": job_id,
        "quality_ok": bool(quality.get("ok")),
        "quality_issue_count": len(quality.get("issues", []) or []),
        "download_url": f"/download/{job_id}",
    }


@app.post("/regenerate-section/{job_id}")
def regenerate_section(job_id: str, body: dict = Body(...)):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state(job_dir(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("done", "failed", "canceled"):
        raise HTTPException(status_code=400, detail="Section regeneration is allowed only after job completion or failure.")

    dbg = read_job_debug(job_id)
    template_key, template_cfg = _load_template_cfg_for_job(job_id, dbg)
    headers = template_cfg.get("writer_format", []) or []
    target = str((body or {}).get("section", "")).strip()
    if not target:
        raise HTTPException(status_code=400, detail="Section is required.")
    if headers and target not in headers:
        raise HTTPException(status_code=400, detail=f"Unknown section '{target}' for template '{template_key}'.")

    report_text = read_job_text(job_id, "report.txt")
    if not report_text.strip():
        raise HTTPException(status_code=400, detail="No report draft available for regeneration.")
    sections = split_by_headers(report_text, headers) if headers else {}
    if headers and target not in sections:
        raise HTTPException(status_code=400, detail=f"Section '{target}' not found in report draft.")

    theory_text = read_job_text(job_id, "theory.txt")
    current_section = sections.get(target, "") if headers else ""
    extra = str((body or {}).get("instructions", "")).strip()
    data_summary = (((dbg.get("agent_status") or {}).get("data") or {}).get("payload") or {}).get("data_summary", {})

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

ADDITIONAL INSTRUCTIONS:
{extra or "(none)"}
"""
    new_body = (chat(system, user) or "").strip()
    if not new_body:
        raise HTTPException(status_code=500, detail="Model returned empty section content.")

    if headers:
        sections[target] = new_body
        new_report = join_sections(sections, headers)
    else:
        new_report = report_text

    write_job_text(job_id, "report.txt", new_report)
    upsert_job_debug(job_id, {"report_sections": sections})
    _rebuild_pdf_for_job(job_id, dbg, template_cfg)
    return {"ok": True, "job_id": job_id, "section": target, "download_url": f"/download/{job_id}"}


@app.get("/job/{job_id}")
def job_page(request: Request, job_id: str):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    st = read_state(job_dir(job_id))
    if not st:
        # render friendly "not found"
        return templates.TemplateResponse(
            "job.html",
            {"request": request, "job_id": job_id, "state": None},
            status_code=404,
        )

    return templates.TemplateResponse(
        "job.html",
        {"request": request, "job_id": job_id, "state": st.__dict__},
    )


@app.get("/status/{job_id}")
def job_status(job_id: str):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    st = read_state(job_dir(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")

    payload = dict(st.__dict__)
    debug_path = job_dir(job_id) / "debug.json"
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


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str, x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")):
    _require_admin_key(x_admin_key)
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    jdir = job_dir(job_id)
    st = read_state(jdir)
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")

    if st.status in ("done", "failed", "canceled"):
        return {"job_id": job_id, "status": st.status, "message": "Job is already finished."}

    st.cancellation_requested = True
    st.stage = "cancel_requested"
    write_state(jdir, st)
    _log_event("job_cancel_requested", job_id=job_id, status=st.status)
    return {"job_id": job_id, "status": st.status, "message": "Cancellation requested."}


@app.post("/cleanup")
def cleanup(
    max_age_hours: int = 24 * 7,
    dry_run: bool = True,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
    _require_admin_key(x_admin_key)
    return cleanup_artifacts(max_age_hours=max_age_hours, dry_run=dry_run)


@app.get("/download/{job_id}")
def download(job_id: str):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")

    pdf = job_pdf_path(job_id)
    if not pdf.exists():
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(
        str(pdf),
        media_type="application/pdf",
        filename=f"{job_id}.pdf",
    )


def _validate_csv(csv_path: str) -> dict:
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read CSV. Make sure it is a valid .csv file.")

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


def _log_event(event: str, *, job_id: str, **fields) -> None:
    payload = {"event": event, "job_id": job_id, **fields}
    logger.info(json.dumps(payload, sort_keys=True))


def _set_stage(st, jdir, *, stage: str, progress_pct: int) -> None:
    st.stage = stage
    st.progress_pct = max(0, min(100, int(progress_pct)))
    write_state(jdir, st)


def _queue_pipeline_job(
    *,
    background_tasks: BackgroundTasks,
    payload: dict,
    retry_of: str | None = None,
) -> tuple[str, dict, dict]:
    template = payload["template"]
    template_cfg = get_template(template)
    csv_path = payload.get("csv_path")
    if csv_path and not os.path.exists(csv_path):
        raise HTTPException(status_code=400, detail="Retry source CSV is missing on disk.")

    job_id = new_job_id()
    jdir = job_dir(job_id)
    st = new_state(job_id)
    write_state(jdir, st)

    worker_kwargs = {
        "job_id": job_id,
        "manual_text": payload["manual_text"],
        "goal": payload["goal"],
        "csv_path": csv_path,
        "extra_instructions": payload["extra_instructions"],
        "template": template,
        "template_cfg": template_cfg,
        "include_review_bool": bool(payload.get("include_review_bool", False)),
        "csv_info": payload.get("csv_info", {}),
        "meta": payload["meta"],
    }
    queue_res = enqueue_job(
        background_tasks=background_tasks,
        worker_callable=_execute_job,
        worker_path="main._execute_job",
        worker_kwargs=worker_kwargs,
    )
    if queue_res.mode == "rq_error":
        raise HTTPException(status_code=503, detail=f"Queue unavailable: {queue_res.error}")

    st.queue_mode = queue_res.mode
    st.queue_job_id = queue_res.job_id
    write_state(jdir, st)

    write_job_debug(
        job_id,
        {
            "template": template,
            "template_display_name": template_cfg.get("display_name", template),
            "has_csv": bool(csv_path),
            "request_payload": payload,
            "queue_mode": queue_res.mode,
            "queue_job_id": queue_res.job_id,
            "retry_of": retry_of,
        },
    )
    return job_id, queue_res.__dict__, template_cfg


def _require_admin_key(x_admin_key: str | None) -> None:
    if not ADMIN_API_KEY:
        return
    if x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _check_rate_limit(request: Request) -> None:
    if not RATE_LIMIT_ENABLED:
        return
    ip = (request.client.host if request.client else None) or "unknown"
    now = monotonic()
    with RATE_LIMIT_LOCK:
        q = RATE_LIMIT_BUCKETS[ip]
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {RATE_LIMIT_MAX_REQUESTS} requests/{RATE_LIMIT_WINDOW_SECONDS}s",
            )
        q.append(now)


def _validate_text_lengths(
    *,
    report_title: str,
    student_name: str,
    course: str,
    group: str,
    date: str,
    goal: str,
    extra_instructions: str,
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
        "manual_text": (final_manual_text, 400000),
    }
    for field, (value, max_len) in limits.items():
        if len((value or "").strip()) > max_len:
            raise HTTPException(status_code=400, detail=f"Field '{field}' is too long (max {max_len} chars).")


def _validate_template_inputs(
    *,
    template_key: str,
    template_cfg: dict,
    has_csv: bool,
    include_review_bool: bool,
    goal: str,
) -> None:
    schema = template_cfg.get("form_schema", {}) or {}
    allow_csv = bool(schema.get("allow_csv", True))
    require_csv = bool(schema.get("require_csv", template_cfg.get("needs_csv", False)))
    allow_review = bool(schema.get("allow_review", template_cfg.get("include_review", False)))
    goal_min_len = int(schema.get("goal_min_len", 0))

    if require_csv and not has_csv:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' requires a CSV upload.")
    if not allow_csv and has_csv:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' does not accept CSV uploads.")
    if include_review_bool and not allow_review:
        raise HTTPException(status_code=400, detail=f"Template '{template_key}' does not support reviewer feedback.")

    if len((goal or "").strip()) < goal_min_len:
        raise HTTPException(
            status_code=400,
            detail=f"Template '{template_key}' requires goal length >= {goal_min_len} characters.",
        )


@app.post("/run")
async def run(
    request: Request,
    background_tasks: BackgroundTasks,
    template: str = Form(DEFAULT_TEMPLATE),

    manual_text: str = Form(""),
    manual_pdf: UploadFile | None = File(None),

    report_title: str = Form(""),
    student_name: str = Form(""),
    course: str = Form(""),
    group: str = Form(""),
    date: str = Form(""),

    goal: str = Form("Generate a complete report."),
    extra_instructions: str = Form(""),

    data_csv: UploadFile | None = File(None),

    include_review: str = Form("0"),
):
    _check_rate_limit(request)
    # template config
    try:
        template_cfg = get_template(template)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown template: {template}")

    include_review_bool = (include_review == "1")

    # manual: pdf OR text
    extracted_manual_text = ""
    has_manual_pdf = (
        manual_pdf is not None
        and getattr(manual_pdf, "filename", None)
        and manual_pdf.filename.strip() != ""
    )

    if has_manual_pdf:
        try:
            pdf_path = save_upload(manual_pdf, allowed_extensions={".pdf"})
            pdf_max_pages = int(os.getenv("PDF_MAX_PAGES", "0"))
            extracted_manual_text = pdf_to_text(pdf_path, max_pages=pdf_max_pages if pdf_max_pages > 0 else None)
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

    # csv handling
    csv_path = None
    csv_info = {"rows": 0, "cols": 0, "columns": [], "numeric_columns": [], "preview_head": []}

    has_csv = (
        data_csv is not None
        and getattr(data_csv, "filename", None)
        and data_csv.filename.strip() != ""
    )

    _validate_template_inputs(
        template_key=template,
        template_cfg=template_cfg,
        has_csv=bool(has_csv),
        include_review_bool=include_review_bool,
        goal=goal,
    )

    if has_csv:
        try:
            csv_path = save_upload(data_csv, allowed_extensions={".csv"})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        csv_info = _validate_csv(csv_path)

    _validate_text_lengths(
        report_title=report_title,
        student_name=student_name,
        course=course,
        group=group,
        date=date,
        goal=goal,
        extra_instructions=extra_instructions,
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

    request_payload = {
        "template": template,
        "manual_text": final_manual_text,
        "goal": goal,
        "csv_path": csv_path,
        "extra_instructions": extra_instructions,
        "include_review_bool": include_review_bool,
        "csv_info": csv_info,
        "meta": meta,
    }
    job_id, queue_res, _ = _queue_pipeline_job(
        background_tasks=background_tasks,
        payload=request_payload,
    )

    # return job page URL so UI can redirect
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
        "summary": {
            "template_name": template_cfg.get("display_name", template),
            "include_review": bool(include_review_bool and template_cfg.get("include_review", False)),
            "csv_rows": csv_info["rows"],
            "csv_columns": csv_info["columns"],
            "numeric_columns": csv_info["numeric_columns"],
            "plots_generated": [],
        },
    }


@app.post("/retry/{job_id}")
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
):
    if not is_safe_job_id(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    st = read_state(job_dir(job_id))
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")
    if st.status not in ("failed", "canceled"):
        raise HTTPException(status_code=400, detail="Only failed/canceled jobs can be retried.")

    dbg = read_job_debug(job_id)
    payload = dbg.get("request_payload") if isinstance(dbg, dict) else None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Retry data unavailable for this job.")

    for key in ("template", "manual_text", "goal", "extra_instructions", "csv_info", "meta"):
        if key not in payload:
            raise HTTPException(status_code=400, detail=f"Retry payload missing required key: {key}")

    new_job_id_value, queue_res, template_cfg = _queue_pipeline_job(
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
        "summary": {
            "template_name": template_cfg.get("display_name", payload["template"]),
            "include_review": bool(payload.get("include_review_bool", False) and template_cfg.get("include_review", False)),
            "csv_rows": (payload.get("csv_info") or {}).get("rows", 0),
            "csv_columns": (payload.get("csv_info") or {}).get("columns", []),
            "numeric_columns": (payload.get("csv_info") or {}).get("numeric_columns", []),
            "plots_generated": [],
        },
    }


def _execute_job(
    *,
    job_id: str,
    manual_text: str,
    goal: str,
    csv_path: str | None,
    extra_instructions: str,
    template: str,
    template_cfg: dict,
    include_review_bool: bool,
    csv_info: dict,
    meta: dict,
) -> None:
    jdir = job_dir(job_id)
    st = read_state(jdir)
    if not st:
        return

    pdf_path = job_pdf_path(job_id)
    _log_event("job_worker_started", job_id=job_id, has_csv=bool(csv_path), template=template)

    try:
        if st.cancellation_requested:
            st.status = "canceled"
            st.error = "Canceled by user."
            _set_stage(st, jdir, stage="canceled", progress_pct=100)
            return

        st.status = "running"
        st.error = None
        _set_stage(st, jdir, stage="starting", progress_pct=5)
        _log_event("job_status_updated", job_id=job_id, status=st.status)

        t_pipeline = perf_counter()

        def on_progress(stage: str, meta: dict) -> None:
            _set_stage(
                st,
                jdir,
                stage=stage,
                progress_pct=meta.get("progress_pct", st.progress_pct),
            )

        def is_canceled() -> bool:
            latest = read_state(jdir)
            return bool(latest and latest.cancellation_requested)

        result = run_pipeline(
            job_id=job_id,
            manual_text=manual_text,
            goal=goal,
            csv_path=csv_path,
            extra_instructions=extra_instructions,
            template_cfg=template_cfg,
            include_review=include_review_bool,
            progress_cb=on_progress,
            should_cancel=is_canceled,
        )
        pipeline_ms = int((perf_counter() - t_pipeline) * 1000)
        _log_event("pipeline_completed", job_id=job_id, duration_ms=pipeline_ms)

        try:
            upsert_job_debug(
                job_id,
                {
                    "template": template,
                    "template_display_name": template_cfg.get("display_name", template),
                    "include_review_requested": bool(include_review_bool),
                    "include_review_effective": bool(include_review_bool and template_cfg.get("include_review", False)),
                    "has_csv": bool(csv_path),
                    "agent_status": result.get("agent_status", {}),
                    "report_sections": result.get("report_sections", {}),
                    "quality": result.get("quality", {}),
                    "pipeline_duration_ms": pipeline_ms,
                },
            )
            write_job_text(job_id, "theory.txt", result.get("theory", ""))
            write_job_text(job_id, "report.txt", result.get("report", ""))
            write_job_text(job_id, "review.txt", result.get("review", ""))
            write_job_text(job_id, "figures.txt", result.get("figures", ""))
        except Exception:
            pass

        plot_paths = {}
        if template_cfg.get("include_plots", False) and csv_path:
            if is_canceled():
                raise CancelledError("Job canceled by user.")
            _set_stage(st, jdir, stage="plotting", progress_pct=90)
            t_plots = perf_counter()
            plot_paths = generate_plots(csv_path, job_id=job_id)
            _log_event(
                "plots_generated",
                job_id=job_id,
                duration_ms=int((perf_counter() - t_plots) * 1000),
                count=len(plot_paths),
            )

        review_text = result.get("review", "")
        if not (include_review_bool and template_cfg.get("include_review", False)):
            review_text = ""

        if is_canceled():
            raise CancelledError("Job canceled by user.")
        _set_stage(st, jdir, stage="pdf_build", progress_pct=95)
        t_pdf = perf_counter()
        build_submission_pdf(
            out_path=str(pdf_path),
            meta=meta,
            source_summary=result.get("theory", ""),
            report_text=result.get("report", ""),
            review_text=review_text,
            data_preview=result.get("data_summary", {}).get("preview_head", csv_info["preview_head"]),
            plot_paths=plot_paths,
        )
        _log_event(
            "pdf_built",
            job_id=job_id,
            duration_ms=int((perf_counter() - t_pdf) * 1000),
            path=str(pdf_path),
        )

        st.status = "done"
        st.error = None
        _set_stage(st, jdir, stage="done", progress_pct=100)
        _log_event("job_status_updated", job_id=job_id, status=st.status)
    except CancelledError as e:
        st.status = "canceled"
        st.error = str(e)
        _set_stage(st, jdir, stage="canceled", progress_pct=100)
        _log_event("job_status_updated", job_id=job_id, status=st.status, error=st.error)
    except Exception as e:
        st.status = "failed"
        st.error = f"{type(e).__name__}: {e}"
        _set_stage(st, jdir, stage="failed", progress_pct=100)
        _log_event("job_status_updated", job_id=job_id, status=st.status, error=st.error)
        try:
            upsert_job_debug(
                job_id,
                {
                    "template": template,
                    "template_display_name": template_cfg.get("display_name", template),
                    "include_review_requested": bool(include_review_bool),
                    "include_review_effective": bool(include_review_bool and template_cfg.get("include_review", False)),
                    "has_csv": bool(csv_path),
                    "error": st.error,
                },
            )
        except Exception:
            pass
