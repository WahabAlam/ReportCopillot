"""Service-layer logic for submission service."""

from __future__ import annotations

import os

from fastapi import HTTPException

from utils.jobs import new_job_id, job_dir, write_job_debug
from utils.queue import enqueue_job
from utils.state import new_state, write_state


def normalize_print_profile(
    value: str | None,
    *,
    default_print_profile: str,
    allowed_print_profiles: tuple[str, ...],
    strict: bool = False,
) -> str:
    # Normalize user-supplied values while optionally enforcing strict validation.
    profile = str(value or default_print_profile).strip().lower()
    if profile in allowed_print_profiles:
        return profile
    if strict:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid print_profile '{profile}'. Allowed: {', '.join(allowed_print_profiles)}.",
        )
    return default_print_profile


def build_job_summary(*, template_cfg: dict, payload: dict, default_print_profile: str) -> dict:
    # Summary is used by the UI right after enqueue.
    csv_info = payload.get("csv_info") or {}
    return {
        "template_name": template_cfg.get("display_name", payload.get("template", "")),
        "include_review": bool(payload.get("include_review_bool", False) and template_cfg.get("include_review", False)),
        "csv_rows": csv_info.get("rows", 0),
        "csv_columns": csv_info.get("columns", []),
        "numeric_columns": csv_info.get("numeric_columns", []),
        "image_count": len(payload.get("image_assets") or []),
        "print_profile": payload.get("print_profile", default_print_profile),
        "plots_generated": [],
    }


def queue_pipeline_job(
    *,
    background_tasks,
    payload: dict,
    retry_of: str | None = None,
    get_template_fn,
    resolve_template_cfg_fn,
    apply_layout_section_headers_fn,
    worker_callable,
    worker_path: str,
    default_print_profile: str,
    allowed_print_profiles: tuple[str, ...],
) -> tuple[str, dict, dict]:
    # Normalize payload first so retries and fresh runs behave consistently.
    payload = dict(payload or {})
    payload["print_profile"] = normalize_print_profile(
        payload.get("print_profile"),
        default_print_profile=default_print_profile,
        allowed_print_profiles=allowed_print_profiles,
        strict=False,
    )

    template = payload["template"]
    csv_path = payload.get("csv_path")
    template_cfg = resolve_template_cfg_fn(get_template_fn(template), has_csv=bool(csv_path))
    template_cfg = apply_layout_section_headers_fn(template_cfg, payload.get("layout_section_headers") or [])
    if csv_path and not os.path.exists(csv_path):
        raise HTTPException(status_code=400, detail="Retry source CSV is missing on disk.")
    image_assets = payload.get("image_assets") or []
    for asset in image_assets:
        path = (asset or {}).get("path")
        if path and not os.path.exists(path):
            raise HTTPException(status_code=400, detail="Retry source image is missing on disk.")

    job_id = new_job_id()
    jdir = job_dir(job_id)
    st = new_state(job_id)
    write_state(jdir, st)

    worker_kwargs = {
        "job_id": job_id,
        "manual_text": payload["manual_text"],
        "goal": payload["goal"],
        "csv_path": csv_path,
        "image_assets": image_assets,
        "extra_instructions": payload["extra_instructions"],
        "print_profile": payload.get("print_profile", default_print_profile),
        "template": template,
        "template_cfg": template_cfg,
        "include_review_bool": bool(payload.get("include_review_bool", False)),
        "csv_info": payload.get("csv_info", {}),
        "meta": payload["meta"],
    }
    # Queue backend is resolved in utils.queue (background task vs RQ worker).
    queue_res = enqueue_job(
        background_tasks=background_tasks,
        worker_callable=worker_callable,
        worker_path=worker_path,
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
            "has_images": bool(image_assets),
            "request_payload": payload,
            "queue_mode": queue_res.mode,
            "queue_job_id": queue_res.job_id,
            "retry_of": retry_of,
        },
    )
    return job_id, queue_res.__dict__, template_cfg
