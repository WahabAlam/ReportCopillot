"""Route handler helpers for system handlers."""

from __future__ import annotations

from pathlib import Path


def template_configs_payload(
    *,
    templates_map: dict,
    default_template: str,
    default_print_profile: str,
    get_print_profile_options_fn,
    admin_api_key: str,
    rate_limit_enabled: bool,
    rate_limit_max_requests: int,
    rate_limit_window_seconds: int,
    use_rq_queue: bool,
    rq_queue_name: str,
) -> dict:
    # Publish a UI-safe subset of template config plus runtime toggles.
    public = {}
    for key, cfg in templates_map.items():
        schema = cfg.get("form_schema", {}) or {}
        public[key] = {
            "display_name": cfg.get("display_name", key),
            "pdf_title_default": cfg.get("pdf_title_default", "Report"),
            "needs_csv": bool(cfg.get("needs_csv", False)),
            "include_review": bool(cfg.get("include_review", False)),
            "include_plots": bool(cfg.get("include_plots", False)),
            "include_source_appendix": bool(cfg.get("include_source_appendix", True)),
            "pdf_theme": cfg.get("pdf_theme", {}),
            "writer_format": cfg.get("writer_format", []),
            "form_schema": {
                "allow_csv": bool(schema.get("allow_csv", True)),
                "require_csv": bool(schema.get("require_csv", cfg.get("needs_csv", False))),
                "allow_review": bool(schema.get("allow_review", cfg.get("include_review", False))),
                "allow_images": bool(schema.get("allow_images", False)),
                "goal_min_len": int(schema.get("goal_min_len", 0)),
                "goal_placeholder": schema.get("goal_placeholder", ""),
                "manual_placeholder": schema.get("manual_placeholder", ""),
                "extra_placeholder": schema.get("extra_placeholder", ""),
            },
        }
    return {
        "default_template": default_template,
        "print_profiles": {
            "default": default_print_profile,
            "options": get_print_profile_options_fn(),
        },
        "templates": public,
        "runtime": {
            "admin_protected_endpoints": bool(admin_api_key),
            "run_rate_limit_enabled": bool(rate_limit_enabled),
            "run_rate_limit_max_requests": rate_limit_max_requests,
            "run_rate_limit_window_seconds": rate_limit_window_seconds,
            "use_rq_queue": bool(use_rq_queue),
            "rq_queue_name": rq_queue_name,
        },
    }


def recent_jobs_payload(
    *,
    limit: int,
    show_all: bool,
    outputs_root: Path,
    is_safe_job_id_fn,
    read_state_fn,
    read_job_debug_fn,
) -> dict:
    # Keep response bounded; list endpoint is for dashboard cards, not full history export.
    limit = max(1, min(int(limit), 50))
    out = []
    if not outputs_root.exists():
        return {"jobs": []}

    for output_dir in outputs_root.iterdir():
        if not output_dir.is_dir():
            continue
        job_id = output_dir.name
        if not is_safe_job_id_fn(job_id):
            continue
        st = read_state_fn(output_dir)
        if not st:
            continue
        dbg = read_job_debug_fn(job_id)
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
