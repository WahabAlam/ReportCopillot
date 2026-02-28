# agents/diagram_agent.py
from __future__ import annotations

import json
from schemas import AgentResult
from utils.llm import chat

def _build_system(template_cfg: dict) -> str:
    template_name = template_cfg.get("display_name", "Report")
    return f"""You suggest helpful figures/plots/diagrams to include in a report.

Template: {template_name}

Rules:
- Suggest 3-5 figures maximum.
- Do NOT invent experimental apparatus details.
- If a CSV/data_summary exists, prioritize plots derived from it (e.g., time-series, histogram, box plot).
- Keep suggestions generic and applicable; do not hardcode numbers from a single dataset.
- Output plain text (no markdown), with clear titles and 1-2 sentences each explaining why it helps.
""".strip()

def run(*, job_id: str, ctx: dict) -> AgentResult:
    try:
        template_cfg = ctx.get("template_cfg") or {}
        theory_text = ctx.get("theory_text", "")
        data_summary = ctx.get("data_summary") or {}

        system = _build_system(template_cfg)
        user = f"""THEORY / NOTES:
{theory_text}

DATA SUMMARY (JSON):
{json.dumps(data_summary or {}, indent=2)}

Suggest figures now."""
        figures_text = chat(system, user)

        return AgentResult.success("diagram", job_id, payload={"figures_text": figures_text})
    except Exception as e:
        return AgentResult.fail("diagram", job_id, "Diagram agent failed", f"{type(e).__name__}: {e}")
