# agents/reviewer_agent.py
from __future__ import annotations

from schemas import AgentResult
from utils.llm import chat

def _build_system(template_cfg: dict) -> str:
    template_name = template_cfg.get("display_name", "Report")

    return f"""You are a careful reviewer.

Task:
- Review the report and return concise reviewer feedback for the student.
- Do not rewrite the report itself.
- Do not invent facts or numbers.
- Point out missing information explicitly.
- Keep feedback practical and specific.

Return format (plain text only):
Strengths:
- ...

Issues to fix:
- ...

Suggested edits:
- ...

Template: {template_name}
""".strip()

def run(*, job_id: str, ctx: dict) -> AgentResult:
    try:
        template_cfg = ctx.get("template_cfg") or {}
        report_text = ctx.get("report_text", "")

        if not report_text.strip():
            return AgentResult.fail("reviewer", job_id, "No report provided to reviewer", None)

        system = _build_system(template_cfg)
        user = f"""REPORT TO REVIEW:
{report_text}

Return reviewer feedback now."""
        feedback = chat(system, user)

        return AgentResult.success(
            "reviewer",
            job_id,
            payload={
                "review_text": feedback,
            },
        )
    except Exception as e:
        return AgentResult.fail("reviewer", job_id, "Reviewer agent failed", f"{type(e).__name__}: {e}")
