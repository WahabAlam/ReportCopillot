"""Pipeline orchestrator that runs agents and assembles final artifacts."""

# orchestrator.py
from __future__ import annotations

from time import perf_counter
from typing import Callable

from agents.research_agent import run as research_run
from agents.data_agent import run as data_run
from agents.writer_agent import run as writer_run
from agents.reviewer_agent import run as reviewer_run
from agents.diagram_agent import run as diagram_run

from schemas import AgentResult
from utils.quality_gate import evaluate_report_quality, build_quality_fix_prompt
from utils.retrieval import build_source_chunks


class CancelledError(RuntimeError):
    """Raised when the worker receives a cooperative cancellation signal."""

    pass


def _merge_instructions(template_cfg: dict, extra_instructions: str) -> str:
    # Keep template-level guidance and per-run overrides in one deterministic text block.
    template_instructions = (template_cfg.get("instructions") or "").strip()
    extra_instructions = (extra_instructions or "").strip()
    merged = "\n\n".join([s for s in [template_instructions, extra_instructions] if s])
    return merged.strip()


def _repair_prompt(missing_headers: list[str], template_cfg: dict) -> str:
    # Force a full rewrite when required section headers are missing.
    required = template_cfg.get("writer_format", [])
    required_list = ", ".join([f"{h}:" for h in required]) if required else "(none)"
    missing_list = ", ".join([f"{h}:" for h in missing_headers])

    return (
        "IMPORTANT FIX PASS:\n"
        f"- Your previous output is missing required sections: {missing_list}\n"
        f"- You MUST output the full report again using ALL required headers exactly.\n"
        f"- Required headers are: {required_list}\n"
        "- Do not add extra headers.\n"
        "- Keep the content consistent; only restructure/expand to include missing sections.\n"
        "- Keep it clean and submission-ready.\n"
    )


def run_pipeline(
    *,
    job_id: str,
    manual_text: str,
    goal: str,
    csv_path: str | None,
    image_assets: list[dict] | None = None,
    extra_instructions: str,
    template_cfg: dict | None = None,
    include_review: bool = False,
    progress_cb: Callable[[str, dict], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    # Normalize optional config once so downstream agents receive a stable context object.
    template_cfg = template_cfg or {}
    merged_instructions = _merge_instructions(template_cfg, extra_instructions)
    source_chunks = build_source_chunks(
        manual_text,
        chunk_chars=int(template_cfg.get("source_chunk_chars", 1200)),
        overlap_chars=int(template_cfg.get("source_overlap_chars", 160)),
    )

    # Base context shared with all agents.
    ctx = {
        "manual_text": manual_text,
        "goal": goal,
        "csv_path": csv_path,
        "image_assets": image_assets or [],
        "preview_rows": int(template_cfg.get("preview_rows", 10)),
        "extra_instructions": merged_instructions,
        "template_cfg": template_cfg,
        "source_chunks": source_chunks,
    }
    timings_ms: dict[str, int] = {}

    # Cancellation is polled between major stages so work stops at safe boundaries.
    def _check_cancel() -> None:
        if should_cancel and should_cancel():
            raise CancelledError("Job canceled by user.")

    # 1) Research stage: extract theory and facts from manual/notes input.
    _check_cancel()
    if progress_cb:
        progress_cb("research", {"progress_pct": 20})
    t0 = perf_counter()
    r1: AgentResult = research_run(job_id=job_id, ctx=ctx)
    timings_ms["research"] = int((perf_counter() - t0) * 1000)
    if not r1.ok:
        raise RuntimeError(f"[research] {r1.error.message}: {r1.error.detail}")
    theory_text = r1.payload.get("theory_text", "")
    research_facts = r1.payload.get("research_facts", {}) or {}

    # 2) Data stage: compute dataset summaries/highlights from CSV when present.
    _check_cancel()
    if progress_cb:
        progress_cb("data", {"progress_pct": 35})
    t0 = perf_counter()
    d1: AgentResult = data_run(job_id=job_id, ctx=ctx)
    timings_ms["data"] = int((perf_counter() - t0) * 1000)
    if not d1.ok:
        raise RuntimeError(f"[data] {d1.error.message}: {d1.error.detail}")
    data_summary = d1.payload.get("data_summary", {})
    data_highlights = d1.payload.get("data_highlights", {}) or {}

    # 3) Writer stage: synthesize full report draft from research + data outputs.
    _check_cancel()
    if progress_cb:
        progress_cb("writer", {"progress_pct": 55})
    ctx2 = dict(ctx)
    ctx2.update(
        {
            "theory_text": theory_text,
            "research_facts": research_facts,
            "data_summary": data_summary,
            "data_highlights": data_highlights,
            "image_assets": image_assets or [],
        }
    )

    t0 = perf_counter()
    w1: AgentResult = writer_run(job_id=job_id, ctx=ctx2)
    timings_ms["writer"] = int((perf_counter() - t0) * 1000)
    if not w1.ok:
        raise RuntimeError(f"[writer] {w1.error.message}: {w1.error.detail}")

    report_text = w1.payload.get("report_text", "")
    sections = w1.payload.get("sections", {}) or {}
    section_sources = w1.payload.get("section_sources", {}) or {}

    # 3b) Structural repair stage: if required sections are missing, do one guided rewrite.
    required_headers = template_cfg.get("writer_format", []) or []
    if required_headers:
        missing = [h for h in required_headers if not (sections.get(h) or "").strip()]
        if missing:
            _check_cancel()
            if progress_cb:
                progress_cb("writer_repair", {"progress_pct": 65})
            fix_instructions = _repair_prompt(missing, template_cfg)
            ctx_fix = dict(ctx2)
            ctx_fix["extra_instructions"] = (merged_instructions + "\n\n" + fix_instructions).strip()

            t0 = perf_counter()
            w2: AgentResult = writer_run(job_id=job_id, ctx=ctx_fix)
            timings_ms["writer_repair"] = int((perf_counter() - t0) * 1000)
            if w2.ok and w2.payload.get("report_text"):
                report_text = w2.payload["report_text"]
                sections = w2.payload.get("sections", {}) or {}
                section_sources = w2.payload.get("section_sources", {}) or {}

    # 4) Reviewer stage (optional): generate feedback text without rewriting report content.
    review_text = ""
    reviewer_status: dict = {"skipped": True}
    if include_review and template_cfg.get("include_review", False):
        _check_cancel()
        if progress_cb:
            progress_cb("reviewer", {"progress_pct": 75})
        t0 = perf_counter()
        rv: AgentResult = reviewer_run(
            job_id=job_id,
            ctx={"report_text": report_text, "template_cfg": template_cfg},
        )
        timings_ms["reviewer"] = int((perf_counter() - t0) * 1000)
        reviewer_status = rv.model_dump()
        if rv.ok:
            review_text = rv.payload.get("review_text", "")
        else:
            review_text = ""

    # 5) Diagram stage (optional): suggest figure ideas based on theory/data summary.
    figures_text = ""
    diagram_status: dict = {"skipped": True}
    if template_cfg.get("include_figures", True) and data_summary:
        _check_cancel()
        if progress_cb:
            progress_cb("diagram", {"progress_pct": 85})
        t0 = perf_counter()
        dg: AgentResult = diagram_run(
            job_id=job_id,
            ctx={"theory_text": theory_text, "data_summary": data_summary, "template_cfg": template_cfg},
        )
        timings_ms["diagram"] = int((perf_counter() - t0) * 1000)
        diagram_status = dg.model_dump()
        if dg.ok:
            figures_text = dg.payload.get("figures_text", "")

    # 6) Quality gate: enforce template quality rules; run one repair pass if needed.
    quality = evaluate_report_quality(report_text, template_cfg)
    if not quality["ok"]:
        if progress_cb:
            progress_cb("quality_fix", {"progress_pct": 88})
        fix_instructions = build_quality_fix_prompt(quality["issues"], template_cfg)
        ctx_q = dict(ctx2)
        ctx_q["extra_instructions"] = (merged_instructions + "\n\n" + fix_instructions).strip()
        t0 = perf_counter()
        wq: AgentResult = writer_run(job_id=job_id, ctx=ctx_q)
        timings_ms["writer_quality_fix"] = int((perf_counter() - t0) * 1000)
        if wq.ok and wq.payload.get("report_text"):
            report_text = wq.payload["report_text"]
            sections = wq.payload.get("sections", {}) or {}
            section_sources = wq.payload.get("section_sources", {}) or {}
        quality = evaluate_report_quality(report_text, template_cfg)

    # Return full payload for worker persistence and PDF assembly.
    return {
        "theory": theory_text,
        "research_facts": research_facts,
        "data_summary": data_summary,
        "data_highlights": data_highlights,
        "image_assets": image_assets or [],
        "report": report_text,
        "review": review_text,
        "figures": figures_text,
        "report_sections": sections,
        "section_sources": section_sources,
        "source_chunks": source_chunks,
        "quality": quality,
        "agent_status": {
            "research": r1.model_dump(),
            "data": d1.model_dump(),
            "writer": w1.model_dump(),
            "reviewer": reviewer_status,
            "diagram": diagram_status,
            "timings_ms": timings_ms,
        },
    }
