# agents/research_agent.py
from __future__ import annotations

from schemas import AgentResult
from utils.llm import chat

SYSTEM = """You extract and summarize theory/notes from the provided manual text.

Rules:
- Only use what the user provided in manual_text.
- If information is missing, list it under "Missing Info / Clarifications Needed".
- Keep it structured and detailed.
- Preserve broad topic coverage from the source (do not collapse many topics into a few bullets).
- Prefer specific, content-rich bullets over generic summaries.

Return format:
Key Concepts:
Variables & Units:
Equations/Models:
Procedure Requirements:
Assumptions (explicitly stated in manual):
Missing Info / Clarifications Needed:
"""


def _split_list(block: str) -> list[str]:
    items: list[str] = []
    for raw in (block or "").splitlines():
        s = raw.strip().lstrip("-").strip()
        if not s:
            continue
        items.extend([p.strip() for p in s.split(";") if p.strip()])
    return items


def _extract_research_facts(theory_text: str) -> dict:
    sections = {
        "key_concepts": "Key Concepts:",
        "variables_units": "Variables & Units:",
        "equations_models": "Equations/Models:",
        "procedure_requirements": "Procedure Requirements:",
        "assumptions": "Assumptions (explicitly stated in manual):",
        "missing_info": "Missing Info / Clarifications Needed:",
    }
    found: dict[str, str] = {k: "" for k in sections}

    current: str | None = None
    for line in (theory_text or "").splitlines():
        stripped = line.strip()
        hit = None
        for k, header in sections.items():
            if stripped.lower() == header.lower():
                hit = k
                break
        if hit is not None:
            current = hit
            continue
        if current is not None:
            found[current] += line + "\n"

    return {
        "key_concepts": _split_list(found["key_concepts"]),
        "variables_units": _split_list(found["variables_units"]),
        "equations_models": _split_list(found["equations_models"]),
        "procedure_requirements": _split_list(found["procedure_requirements"]),
        "assumptions": _split_list(found["assumptions"]),
        "missing_info": _split_list(found["missing_info"]),
    }


def run(*, job_id: str, ctx: dict) -> AgentResult:
    try:
        manual_text = (ctx.get("manual_text") or "").strip()
        goal = (ctx.get("goal") or "").strip()

        user = f"""GOAL:
{goal}

MANUAL / NOTES TEXT:
{manual_text}

Extract the structured theory now."""
        theory_text = chat(SYSTEM, user)
        research_facts = _extract_research_facts(theory_text)

        return AgentResult.success(
            "research",
            job_id,
            payload={"theory_text": theory_text, "research_facts": research_facts},
        )
    except Exception as e:
        return AgentResult.fail("research", job_id, "Research agent failed", f"{type(e).__name__}: {e}")
