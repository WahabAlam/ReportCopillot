"""Service-layer logic for job worker."""

from __future__ import annotations

from time import perf_counter

from utils.jobs import job_dir, job_pdf_path, upsert_job_debug, write_job_text
from utils.plots import generate_plots
from utils.pdf_report import build_submission_pdf
from utils.state import read_state, write_state


def _set_stage(st, jdir, *, stage: str, progress_pct: int) -> None:
    # Clamp progress to prevent invalid UI percentages.
    st.stage = stage
    st.progress_pct = max(0, min(100, int(progress_pct)))
    write_state(jdir, st)


def execute_job(
    *,
    job_id: str,
    manual_text: str,
    goal: str,
    csv_path: str | None,
    image_assets: list[dict] | None,
    extra_instructions: str,
    print_profile: str,
    template: str,
    template_cfg: dict,
    include_review_bool: bool,
    csv_info: dict,
    meta: dict,
    run_pipeline_fn,
    cancelled_error_cls,
    normalize_print_profile_fn,
    log_event_fn,
) -> None:
    # Worker owns end-to-end lifecycle: run agents, render plots/PDF, and persist state.
    jdir = job_dir(job_id)
    st = read_state(jdir)
    if not st:
        return

    pdf_path = job_pdf_path(job_id)
    image_assets = image_assets or []
    print_profile = normalize_print_profile_fn(print_profile, strict=False)
    log_event_fn(
        "job_worker_started",
        job_id=job_id,
        has_csv=bool(csv_path),
        image_count=len(image_assets),
        template=template,
        print_profile=print_profile,
    )

    try:
        if st.cancellation_requested:
            st.status = "canceled"
            st.error = "Canceled by user."
            _set_stage(st, jdir, stage="canceled", progress_pct=100)
            return

        st.status = "running"
        st.error = None
        _set_stage(st, jdir, stage="starting", progress_pct=5)
        log_event_fn("job_status_updated", job_id=job_id, status=st.status)

        t_pipeline = perf_counter()

        # Bridge orchestrator stage callbacks into persisted state updates.
        def on_progress(stage: str, meta: dict) -> None:
            _set_stage(
                st,
                jdir,
                stage=stage,
                progress_pct=meta.get("progress_pct", st.progress_pct),
            )

        # Cooperative cancellation checks persisted state for external cancel requests.
        def is_canceled() -> bool:
            latest = read_state(jdir)
            return bool(latest and latest.cancellation_requested)

        result = run_pipeline_fn(
            job_id=job_id,
            manual_text=manual_text,
            goal=goal,
            csv_path=csv_path,
            image_assets=image_assets,
            extra_instructions=extra_instructions,
            template_cfg=template_cfg,
            include_review=include_review_bool,
            progress_cb=on_progress,
            should_cancel=is_canceled,
        )
        pipeline_ms = int((perf_counter() - t_pipeline) * 1000)
        log_event_fn("pipeline_completed", job_id=job_id, duration_ms=pipeline_ms)

        try:
            upsert_job_debug(
                job_id,
                {
                    "template": template,
                    "template_display_name": template_cfg.get("display_name", template),
                    "include_review_requested": bool(include_review_bool),
                    "include_review_effective": bool(include_review_bool and template_cfg.get("include_review", False)),
                    "has_csv": bool(csv_path),
                    "has_images": bool(image_assets),
                    "print_profile": print_profile,
                    "agent_status": result.get("agent_status", {}),
                    "report_sections": result.get("report_sections", {}),
                    "section_sources": result.get("section_sources", {}),
                    "source_chunk_count": len(result.get("source_chunks", []) or []),
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

        # Plot generation is optional and only meaningful for templates with CSV plots enabled.
        plot_paths = {}
        if template_cfg.get("include_plots", False) and csv_path:
            if is_canceled():
                raise cancelled_error_cls("Job canceled by user.")
            _set_stage(st, jdir, stage="plotting", progress_pct=90)
            t_plots = perf_counter()
            plot_paths = generate_plots(csv_path, job_id=job_id)
            log_event_fn(
                "plots_generated",
                job_id=job_id,
                duration_ms=int((perf_counter() - t_plots) * 1000),
                count=len(plot_paths),
            )

        # Only include reviewer output when both template and request enable it.
        review_text = result.get("review", "")
        if not (include_review_bool and template_cfg.get("include_review", False)):
            review_text = ""

        if is_canceled():
            raise cancelled_error_cls("Job canceled by user.")
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
            uploaded_images=image_assets,
            source_chunks=result.get("source_chunks", []) or [],
            include_source_appendix=bool(template_cfg.get("include_source_appendix", True)),
            theme=template_cfg.get("pdf_theme", {}),
            report_headers=template_cfg.get("writer_format", []),
            print_profile=print_profile,
        )
        log_event_fn(
            "pdf_built",
            job_id=job_id,
            duration_ms=int((perf_counter() - t_pdf) * 1000),
            path=str(pdf_path),
        )

        st.status = "done"
        st.error = None
        _set_stage(st, jdir, stage="done", progress_pct=100)
        log_event_fn("job_status_updated", job_id=job_id, status=st.status)
    except cancelled_error_cls as e:
        st.status = "canceled"
        st.error = str(e)
        _set_stage(st, jdir, stage="canceled", progress_pct=100)
        log_event_fn("job_status_updated", job_id=job_id, status=st.status, error=st.error)
    except Exception as e:
        st.status = "failed"
        st.error = f"{type(e).__name__}: {e}"
        _set_stage(st, jdir, stage="failed", progress_pct=100)
        log_event_fn("job_status_updated", job_id=job_id, status=st.status, error=st.error)
        try:
            upsert_job_debug(
                job_id,
                {
                    "template": template,
                    "template_display_name": template_cfg.get("display_name", template),
                    "include_review_requested": bool(include_review_bool),
                    "include_review_effective": bool(include_review_bool and template_cfg.get("include_review", False)),
                    "has_csv": bool(csv_path),
                    "has_images": bool(image_assets),
                    "print_profile": print_profile,
                    "error": st.error,
                },
            )
        except Exception:
            pass
