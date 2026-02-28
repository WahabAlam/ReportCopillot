# agents/writer_agent.py
from __future__ import annotations

import json
from schemas import AgentResult
from utils.llm import chat
from utils.sections import split_by_headers

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
- Keep the writing clean and submission-ready.
"""
    return base.strip()

def run(*, job_id: str, ctx: dict) -> AgentResult:
    try:
        template_cfg = ctx.get("template_cfg") or {}
        system = _build_system(template_cfg)

        theory_text = ctx.get("theory_text", "")
        research_facts = ctx.get("research_facts") or {}
        data_summary = ctx.get("data_summary") or {}
        data_highlights = ctx.get("data_highlights") or {}
        extra_instructions = ctx.get("extra_instructions") or ""

        user = f"""THEORY / NOTES EXTRACT:
{theory_text}

STRUCTURED RESEARCH FACTS (JSON):
{json.dumps(research_facts, indent=2)}

DATA SUMMARY (JSON):
{json.dumps(data_summary or {}, indent=2)}

DATA HIGHLIGHTS (JSON):
{json.dumps(data_highlights, indent=2)}

EXTRA INSTRUCTIONS:
{extra_instructions}

Prefer the structured facts/highlights when available, and use full data summary for supporting detail.
Write the full document now following the required headers exactly."""
        report_text = chat(system, user)
        writer_format = template_cfg.get("writer_format", []) or []
        sections = split_by_headers(report_text, writer_format) if writer_format else {}

        return AgentResult.success(
            "writer",
            job_id,
            payload={
                "report_text": report_text,
                "sections": sections,
            },
        )
    except Exception as e:
        return AgentResult.fail("writer", job_id, "Writer agent failed", f"{type(e).__name__}: {e}")
