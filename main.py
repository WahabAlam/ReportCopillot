"""FastAPI application entrypoint and endpoint wiring for Report Copilot."""

from __future__ import annotations

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Header, Body
from dotenv import load_dotenv
import json
import logging
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
from utils.pdf_report import (
    DEFAULT_PRINT_PROFILE,
    PRINT_PROFILE_KEYS,
    get_print_profile_options,
)
from utils.jobs import (
    job_pdf_path,
    is_safe_job_id,
    job_dir,
    read_job_debug,
    upsert_job_debug,
    write_job_text,
    read_job_text,
)
from utils.state import write_state, read_state
from utils.cleanup import cleanup_artifacts
from utils.sections import split_by_headers, join_sections
from utils.llm import chat
from utils.request_validation import (
    validate_csv,
    save_image_uploads,
    validate_text_lengths,
    validate_template_inputs,
)
from services.submission_service import (
    normalize_print_profile as normalize_print_profile_service,
    build_job_summary as build_job_summary_service,
    queue_pipeline_job as queue_pipeline_job_service,
)
from services.job_pdf import (
    load_template_cfg_for_job as load_template_cfg_for_job_service,
    rebuild_pdf_for_job as rebuild_pdf_for_job_service,
    apply_quality_fix_for_job as apply_quality_fix_for_job_service,
)
from services.job_worker import execute_job as execute_job_service
from routes.system_handlers import template_configs_payload, recent_jobs_payload
from routes.job_handlers import (
    get_draft_payload,
    save_draft_payload,
    rebuild_job_pdf_payload,
    quality_fix_job_payload,
    regenerate_section_payload,
    job_page_response,
    job_status_payload,
    cancel_job_payload,
    cleanup_payload,
    download_response,
)
from routes.submission_handlers import run_payload, retry_payload

from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles

load_dotenv()
logger = logging.getLogger("report_copilot")
# Runtime policy knobs are intentionally env-driven to keep deploy-time behavior configurable.
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RUN_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RUN_RATE_LIMIT_MAX_REQUESTS", "20"))
RATE_LIMIT_ENABLED = os.getenv("RUN_RATE_LIMIT_ENABLED", "1") == "1"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()
RATE_LIMIT_BUCKETS: dict[str, deque] = defaultdict(deque)
RATE_LIMIT_LOCK = threading.Lock()
USE_RQ_QUEUE = os.getenv("USE_RQ_QUEUE", "0") == "1"
MAX_IMAGE_UPLOADS = int(os.getenv("MAX_IMAGE_UPLOADS", "24"))
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

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
    # Keep endpoint thin: compose payload from a dedicated route handler.
    return template_configs_payload(
        templates_map=TEMPLATES,
        default_template=DEFAULT_TEMPLATE,
        default_print_profile=DEFAULT_PRINT_PROFILE,
        get_print_profile_options_fn=get_print_profile_options,
        admin_api_key=ADMIN_API_KEY,
        rate_limit_enabled=RATE_LIMIT_ENABLED,
        rate_limit_max_requests=RATE_LIMIT_MAX_REQUESTS,
        rate_limit_window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        use_rq_queue=USE_RQ_QUEUE,
        rq_queue_name=os.getenv("RQ_QUEUE_NAME", "report_jobs"),
    )


@app.get("/recent-jobs")
def recent_jobs(limit: int = 10, show_all: bool = False):
    # show_all=False hides synthetic entries (useful for production dashboards).
    return recent_jobs_payload(
        limit=limit,
        show_all=show_all,
        outputs_root=Path("outputs"),
        is_safe_job_id_fn=is_safe_job_id,
        read_state_fn=read_state,
        read_job_debug_fn=read_job_debug,
    )


def _load_template_cfg_for_job(job_id: str, dbg: dict) -> tuple[str, dict]:
    # Service handles fallback inference for older jobs missing explicit template keys.
    return load_template_cfg_for_job_service(job_id, dbg)


def _rebuild_pdf_for_job(job_id: str, dbg: dict, template_cfg: dict) -> None:
    # Re-render from persisted artifacts to support post-run edits/fixes.
    rebuild_pdf_for_job_service(
        job_id,
        dbg,
        template_cfg,
        normalize_print_profile_fn=_normalize_print_profile,
    )


def _apply_quality_fix_for_job(job_id: str, dbg: dict, template_cfg: dict) -> dict:
    # writer_run is injected so tests can monkeypatch main.writer_run and keep behavior deterministic.
    return apply_quality_fix_for_job_service(
        job_id,
        dbg,
        template_cfg,
        normalize_print_profile_fn=_normalize_print_profile,
        writer_run_fn=writer_run,
    )


@app.get("/draft/{job_id}")
def get_draft(job_id: str):
    return get_draft_payload(
        job_id=job_id,
        is_safe_job_id_fn=is_safe_job_id,
        job_dir_fn=job_dir,
        read_state_fn=read_state,
        read_job_debug_fn=read_job_debug,
        load_template_cfg_for_job_fn=_load_template_cfg_for_job,
        read_job_text_fn=read_job_text,
        write_job_text_fn=write_job_text,
        split_by_headers_fn=split_by_headers,
    )


@app.post("/draft/{job_id}")
def save_draft(job_id: str, body: dict = Body(...)):
    return save_draft_payload(
        job_id=job_id,
        body=body,
        is_safe_job_id_fn=is_safe_job_id,
        job_dir_fn=job_dir,
        read_state_fn=read_state,
        read_job_debug_fn=read_job_debug,
        load_template_cfg_for_job_fn=_load_template_cfg_for_job,
        split_by_headers_fn=split_by_headers,
        write_job_text_fn=write_job_text,
        upsert_job_debug_fn=upsert_job_debug,
    )


@app.post("/rebuild/{job_id}")
def rebuild_job_pdf(job_id: str):
    return rebuild_job_pdf_payload(
        job_id=job_id,
        is_safe_job_id_fn=is_safe_job_id,
        job_dir_fn=job_dir,
        read_state_fn=read_state,
        read_job_debug_fn=read_job_debug,
        load_template_cfg_for_job_fn=_load_template_cfg_for_job,
        rebuild_pdf_for_job_fn=_rebuild_pdf_for_job,
    )


@app.post("/quality-fix/{job_id}")
def quality_fix_job(job_id: str):
    return quality_fix_job_payload(
        job_id=job_id,
        is_safe_job_id_fn=is_safe_job_id,
        job_dir_fn=job_dir,
        read_state_fn=read_state,
        read_job_debug_fn=read_job_debug,
        load_template_cfg_for_job_fn=_load_template_cfg_for_job,
        apply_quality_fix_for_job_fn=_apply_quality_fix_for_job,
    )


@app.post("/regenerate-section/{job_id}")
def regenerate_section(job_id: str, body: dict = Body(...)):
    return regenerate_section_payload(
        job_id=job_id,
        body=body,
        is_safe_job_id_fn=is_safe_job_id,
        job_dir_fn=job_dir,
        read_state_fn=read_state,
        read_job_debug_fn=read_job_debug,
        load_template_cfg_for_job_fn=_load_template_cfg_for_job,
        read_job_text_fn=read_job_text,
        split_by_headers_fn=split_by_headers,
        chat_fn=chat,
        write_job_text_fn=write_job_text,
        upsert_job_debug_fn=upsert_job_debug,
        join_sections_fn=join_sections,
        rebuild_pdf_for_job_fn=_rebuild_pdf_for_job,
    )


@app.get("/job/{job_id}")
def job_page(request: Request, job_id: str):
    return job_page_response(
        request=request,
        job_id=job_id,
        templates_engine=templates,
        is_safe_job_id_fn=is_safe_job_id,
        read_state_fn=read_state,
        job_dir_fn=job_dir,
    )


@app.get("/status/{job_id}")
def job_status(job_id: str):
    return job_status_payload(
        job_id=job_id,
        is_safe_job_id_fn=is_safe_job_id,
        read_state_fn=read_state,
        job_dir_fn=job_dir,
    )


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str, x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")):
    return cancel_job_payload(
        job_id=job_id,
        x_admin_key=x_admin_key,
        require_admin_key_fn=_require_admin_key,
        is_safe_job_id_fn=is_safe_job_id,
        job_dir_fn=job_dir,
        read_state_fn=read_state,
        write_state_fn=write_state,
        log_event_fn=_log_event,
    )


@app.post("/cleanup")
def cleanup(
    max_age_hours: int = 24 * 7,
    dry_run: bool = True,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
):
    return cleanup_payload(
        max_age_hours=max_age_hours,
        dry_run=dry_run,
        x_admin_key=x_admin_key,
        require_admin_key_fn=_require_admin_key,
        cleanup_artifacts_fn=cleanup_artifacts,
    )


@app.get("/download/{job_id}")
def download(job_id: str):
    return download_response(
        job_id=job_id,
        is_safe_job_id_fn=is_safe_job_id,
        job_pdf_path_fn=job_pdf_path,
    )


def _log_event(event: str, *, job_id: str, **fields) -> None:
    # JSON log payloads are easier to index in log backends.
    payload = {"event": event, "job_id": job_id, **fields}
    logger.info(json.dumps(payload, sort_keys=True))


def _normalize_print_profile(value: str | None, *, strict: bool = False) -> str:
    # strict=True is used for request validation; strict=False is used for legacy payload fallback.
    return normalize_print_profile_service(
        value,
        default_print_profile=DEFAULT_PRINT_PROFILE,
        allowed_print_profiles=PRINT_PROFILE_KEYS,
        strict=strict,
    )


def _queue_pipeline_job(
    *,
    background_tasks: BackgroundTasks,
    payload: dict,
    retry_of: str | None = None,
) -> tuple[str, dict, dict]:
    # Queue selection (background vs RQ) is centralized in service layer.
    return queue_pipeline_job_service(
        background_tasks=background_tasks,
        payload=payload,
        retry_of=retry_of,
        get_template_fn=get_template,
        worker_callable=_execute_job,
        worker_path="main._execute_job",
        default_print_profile=DEFAULT_PRINT_PROFILE,
        allowed_print_profiles=PRINT_PROFILE_KEYS,
    )


def _build_job_summary(*, template_cfg: dict, payload: dict) -> dict:
    # Summary drives the UI confirmation card after submission.
    return build_job_summary_service(
        template_cfg=template_cfg,
        payload=payload,
        default_print_profile=DEFAULT_PRINT_PROFILE,
    )


def _require_admin_key(x_admin_key: str | None) -> None:
    # If ADMIN_API_KEY is unset, admin endpoints are intentionally open for local dev.
    if not ADMIN_API_KEY:
        return
    if x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _check_rate_limit(request: Request) -> None:
    # In-memory per-IP sliding window limiter for /run submissions.
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
    print_profile: str = Form(DEFAULT_PRINT_PROFILE),

    data_csv: UploadFile | None = File(None),
    lab_images: list[UploadFile] | None = File(None),
    lab_image_titles: list[str] | None = Form(None),
    lab_image_captions: list[str] | None = Form(None),
    lab_image_sections: list[str] | None = Form(None),

    include_review: str = Form("0"),
):
    # Submission handler validates uploads/inputs, persists artifacts, and enqueues a worker job.
    return await run_payload(
        request=request,
        background_tasks=background_tasks,
        template=template,
        manual_text=manual_text,
        manual_pdf=manual_pdf,
        report_title=report_title,
        student_name=student_name,
        course=course,
        group=group,
        date=date,
        goal=goal,
        extra_instructions=extra_instructions,
        print_profile=print_profile,
        data_csv=data_csv,
        lab_images=lab_images,
        lab_image_titles=lab_image_titles,
        lab_image_captions=lab_image_captions,
        lab_image_sections=lab_image_sections,
        include_review=include_review,
        check_rate_limit_fn=_check_rate_limit,
        get_template_fn=get_template,
        normalize_print_profile_fn=_normalize_print_profile,
        save_upload_fn=save_upload,
        pdf_to_text_fn=pdf_to_text,
        validate_template_inputs_fn=validate_template_inputs,
        validate_csv_fn=validate_csv,
        save_image_uploads_fn=save_image_uploads,
        validate_text_lengths_fn=validate_text_lengths,
        queue_pipeline_job_fn=_queue_pipeline_job,
        build_job_summary_fn=_build_job_summary,
        max_image_uploads=MAX_IMAGE_UPLOADS,
        image_extensions=IMAGE_EXTENSIONS,
    )


@app.post("/retry/{job_id}")
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
):
    # Retry handler rebuilds a new queued job from a failed/canceled job's saved payload.
    return await retry_payload(
        job_id=job_id,
        background_tasks=background_tasks,
        is_safe_job_id_fn=is_safe_job_id,
        read_state_fn=read_state,
        job_dir_fn=job_dir,
        read_job_debug_fn=read_job_debug,
        queue_pipeline_job_fn=_queue_pipeline_job,
        build_job_summary_fn=_build_job_summary,
    )


def _execute_job(
    *,
    job_id: str,
    manual_text: str,
    goal: str,
    csv_path: str | None,
    image_assets: list[dict] | None = None,
    extra_instructions: str,
    print_profile: str,
    template: str,
    template_cfg: dict,
    include_review_bool: bool,
    csv_info: dict,
    meta: dict,
) -> None:
    # Keep _execute_job in main as a stable import path for background and RQ workers.
    execute_job_service(
        job_id=job_id,
        manual_text=manual_text,
        goal=goal,
        csv_path=csv_path,
        image_assets=image_assets,
        extra_instructions=extra_instructions,
        print_profile=print_profile,
        template=template,
        template_cfg=template_cfg,
        include_review_bool=include_review_bool,
        csv_info=csv_info,
        meta=meta,
        run_pipeline_fn=run_pipeline,
        cancelled_error_cls=CancelledError,
        normalize_print_profile_fn=_normalize_print_profile,
        log_event_fn=_log_event,
    )
