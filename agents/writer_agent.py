"""Agent implementation for writer agent."""

# agents/writer_agent.py
from __future__ import annotations

import json
import re
from schemas import AgentResult
from utils.llm import chat
from utils.retrieval import extract_source_tags, select_relevant_chunks
from utils.sections import split_by_headers, join_sections

def _build_system(template_cfg: dict) -> str:
    template_name = template_cfg.get("display_name", "Report")
    writer_format = template_cfg.get("writer_format", [])
    writer_rules = template_cfg.get("writer_rules", [])

    if writer_format:
        header_block = "\n".join([f"{h}:" for h in writer_format])
        format_note = (
            "STRICT FORMAT (use these exact headers, each on its own line, exactly as written):\n"
            f"{header_block}\n"
        )
    else:
        format_note = "STRUCTURE: Use clear section headers appropriate for the template.\n"

    rules_block = ""
    if writer_rules:
        rules_block = "Rules:\n" + "\n".join([f"- {r}" for r in writer_rules]) + "\n"

    base = f"""You are a helpful, high-quality writer producing a submission-ready document.
Write in a clear, natural student tone (not AI-sounding).

Template: {template_name}

{format_note}
{rules_block}
General rules:
- Use plain text headers exactly (no bold, no markdown).
- Do not invent facts, equipment models, settings, or numbers not supported by the provided manual_text or data summary.
- If details are missing, label them as assumptions explicitly.
- If uploaded images are provided, reference them as [Image N] where relevant.
- Treat user-provided image titles/captions as authoritative context.
- Do not claim detailed visual observations that are not supported by provided context.
- Keep the writing clean and submission-ready.
"""
    return base.strip()


def _build_section_system(template_cfg: dict, section_name: str) -> str:
    template_name = template_cfg.get("display_name", "Report")
    writer_rules = template_cfg.get("writer_rules", [])
    rules_block = "\n".join([f"- {r}" for r in writer_rules]) if writer_rules else "- Follow the template constraints."
    return f"""You write exactly one section of a larger report.

Template: {template_name}
Section: {section_name}

Rules:
{rules_block}
- Return only the body text for this section (do NOT include the section header).
- Keep the prose detailed and submission-ready.
- Do not invent facts, equipment models, settings, or numbers.
- If source chunks are provided with [S#] IDs, cite factual claims using inline tags like [S3].
- If key details are missing, state assumptions explicitly.
- If image context is relevant, reference images as [Image N].
""".strip()


def _prepare_writer_images(image_assets: list[dict]) -> list[dict]:
    out: list[dict] = []
    for asset in image_assets:
        if not isinstance(asset, dict):
            continue
        out.append(
            {
                "label": asset.get("label", ""),
                "title": asset.get("title", ""),
                "filename": asset.get("filename", ""),
                "caption": asset.get("caption", ""),
                "target_section": asset.get("target_section", ""),
                "suggested_sections": asset.get("suggested_sections", []),
            }
        )
    return out


def _normalize_section_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _filter_images_for_section(writer_images: list[dict], section_name: str) -> list[dict]:
    key = _normalize_section_name(section_name)
    out: list[dict] = []
    for image in writer_images:
        target = _normalize_section_name(str(image.get("target_section", "")))
        suggestions = [_normalize_section_name(str(v)) for v in (image.get("suggested_sections") or []) if str(v).strip()]
        if key and (target == key or key in suggestions):
            out.append(image)
    return out


def _format_source_chunks(chunks: list[dict], *, max_chunk_chars: int = 900) -> str:
    rows: list[str] = []
    for chunk in (chunks or []):
        cid = str(chunk.get("id", "")).strip()
        txt = str(chunk.get("text", "")).strip()
        if not cid or not txt:
            continue
        if len(txt) > max_chunk_chars:
            txt = txt[:max_chunk_chars].rstrip() + "..."
        rows.append(f"[{cid}]\n{txt}")
    return "\n\n".join(rows)


def _sanitize_section_body(raw_text: str, section_name: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""
    prefix = f"{section_name}:"
    if text[: len(prefix)].lower() == prefix.lower():
        text = text[len(prefix) :].strip()
    return text.strip()


def _ensure_section_source_tag(text: str, selected_chunks: list[dict]) -> str:
    if extract_source_tags(text):
        return text
    if not selected_chunks:
        return text
    first_id = str(selected_chunks[0].get("id", "")).strip()
    if not first_id:
        return text
    body = text.rstrip()
    if not body:
        body = "Source-aligned summary."
    return f"{body} [{first_id}]"


def _write_section(
    *,
    section_name: str,
    goal: str,
    template_cfg: dict,
    theory_text: str,
    research_facts: dict,
    data_summary: dict,
    data_highlights: dict,
    writer_images: list[dict],
    extra_instructions: str,
    source_chunks: list[dict],
    source_top_k: int,
) -> tuple[str, list[str], list[str]]:
    section_images = _filter_images_for_section(writer_images, section_name)
    retrieval_query = (
        f"Goal: {goal}\n"
        f"Section: {section_name}\n"
        f"Extra Instructions: {extra_instructions}\n"
        f"Research Facts: {json.dumps(research_facts or {}, ensure_ascii=True)}\n"
        f"Data Highlights: {json.dumps(data_highlights or {}, ensure_ascii=True)}"
    )
    selected_chunks = select_relevant_chunks(retrieval_query, source_chunks, top_k=source_top_k)
    source_block = _format_source_chunks(selected_chunks)

    system = _build_section_system(template_cfg, section_name)
    user = f"""GOAL:
{goal}

SECTION HEADER:
{section_name}

THEORY / NOTES EXTRACT:
{theory_text}

STRUCTURED RESEARCH FACTS (JSON):
{json.dumps(research_facts or {}, indent=2)}

DATA SUMMARY (JSON):
{json.dumps(data_summary or {}, indent=2)}

DATA HIGHLIGHTS (JSON):
{json.dumps(data_highlights or {}, indent=2)}

SECTION-RELEVANT IMAGE CONTEXT (JSON):
{json.dumps(section_images, indent=2)}

SOURCE CHUNKS (with [S#] ids):
{source_block or "(none)"}

EXTRA INSTRUCTIONS:
{extra_instructions}
"""
    body = _sanitize_section_body(chat(system, user), section_name)
    body = _ensure_section_source_tag(body, selected_chunks)
    tags = extract_source_tags(body)
    used_ids = [str(c.get("id", "")).strip() for c in selected_chunks if str(c.get("id", "")).strip()]
    return body, tags, used_ids


def run(*, job_id: str, ctx: dict) -> AgentResult:
    try:
        template_cfg = ctx.get("template_cfg") or {}
        writer_format = template_cfg.get("writer_format", []) or []
        goal = ctx.get("goal", "")
        theory_text = ctx.get("theory_text", "")
        research_facts = ctx.get("research_facts") or {}
        data_summary = ctx.get("data_summary") or {}
        data_highlights = ctx.get("data_highlights") or {}
        image_assets = ctx.get("image_assets") or []
        extra_instructions = ctx.get("extra_instructions") or ""
        source_chunks = ctx.get("source_chunks") or []
        source_top_k = max(2, int(ctx.get("source_top_k_per_section", 6)))
        writer_images = _prepare_writer_images(image_assets)

        if writer_format and source_chunks:
            sections: dict[str, str] = {}
            section_sources: dict[str, list[str]] = {}
            used_source_ids: set[str] = set()
            for section_name in writer_format:
                body, tags, selected_ids = _write_section(
                    section_name=section_name,
                    goal=goal,
                    template_cfg=template_cfg,
                    theory_text=theory_text,
                    research_facts=research_facts,
                    data_summary=data_summary,
                    data_highlights=data_highlights,
                    writer_images=writer_images,
                    extra_instructions=extra_instructions,
                    source_chunks=source_chunks,
                    source_top_k=source_top_k,
                )
                sections[section_name] = body
                section_sources[section_name] = tags
                used_source_ids.update(selected_ids)

            report_text = join_sections(sections, writer_format)
            return AgentResult.success(
                "writer",
                job_id,
                payload={
                    "report_text": report_text,
                    "sections": sections,
                    "section_sources": section_sources,
                    "source_chunks_used": sorted(used_source_ids),
                },
            )

        # Fallback single-pass mode when template has no fixed sections or source chunks are unavailable.
        system = _build_system(template_cfg)
        selected_chunks = select_relevant_chunks(
            f"{goal}\n{extra_instructions}\n{json.dumps(research_facts or {}, ensure_ascii=True)}",
            source_chunks,
            top_k=12,
        ) if source_chunks else []

        user = f"""THEORY / NOTES EXTRACT:
{theory_text}

STRUCTURED RESEARCH FACTS (JSON):
{json.dumps(research_facts, indent=2)}

DATA SUMMARY (JSON):
{json.dumps(data_summary or {}, indent=2)}

DATA HIGHLIGHTS (JSON):
{json.dumps(data_highlights, indent=2)}

UPLOADED IMAGE CONTEXT (JSON):
{json.dumps(writer_images, indent=2)}

SOURCE CHUNKS (with [S#] ids):
{_format_source_chunks(selected_chunks) or "(none)"}

EXTRA INSTRUCTIONS:
{extra_instructions}

Prefer the structured facts/highlights when available, and use full data summary for supporting detail.
If image context is present, reference relevant items using labels like [Image 1] and prefer each image's target_section/caption.
Write the full document now following the required headers exactly."""
        report_text = chat(system, user)
        sections = split_by_headers(report_text, writer_format) if writer_format else {}
        section_sources = {sec: extract_source_tags(body) for sec, body in sections.items()}

        return AgentResult.success(
            "writer",
            job_id,
            payload={
                "report_text": report_text,
                "sections": sections,
                "section_sources": section_sources,
                "source_chunks_used": [str(c.get("id", "")).strip() for c in selected_chunks if str(c.get("id", "")).strip()],
            },
        )
    except Exception as e:
        return AgentResult.fail("writer", job_id, "Writer agent failed", f"{type(e).__name__}: {e}")
