"""Tests for writer agent section behavior."""

from __future__ import annotations

import re

import agents.writer_agent as writer_agent


def _extract_section_name(user_prompt: str) -> str:
    match = re.search(r"SECTION HEADER:\n(.+?)\n", user_prompt)
    return match.group(1).strip() if match else "Section"


def test_writer_uses_prior_sections_as_coherence_context(monkeypatch):
    prompts: list[str] = []

    def fake_chat(system: str, user: str) -> str:
        prompts.append(user)
        section = _extract_section_name(user)
        return f"{section} generated content [S1]"

    monkeypatch.setattr(writer_agent, "chat", fake_chat)

    out = writer_agent.run(
        job_id="WriterCtx1234",
        ctx={
            "template_cfg": {
                "writer_format": ["Objective", "Discussion"],
                "quality": {"min_source_tags_per_section": 0},
            },
            "goal": "Write sections.",
            "theory_text": "Theory",
            "research_facts": {},
            "data_summary": {},
            "data_highlights": {},
            "source_chunks": [{"id": "S1", "text": "Source chunk."}],
            "extra_instructions": "",
        },
    )

    assert out.ok is True
    assert len(prompts) >= 2
    # Second section prompt should include prior section summary lines for coherence.
    assert "EARLIER APPROVED SECTIONS" in prompts[1]
    assert "Objective:" in prompts[1]


def test_writer_rewrite_mode_only_rewrites_target_sections(monkeypatch):
    called_sections: list[str] = []

    def fake_chat(system: str, user: str) -> str:
        section = _extract_section_name(user)
        called_sections.append(section)
        if section == "Discussion":
            return "Updated discussion body [S2]"
        return "Unexpected call"

    monkeypatch.setattr(writer_agent, "chat", fake_chat)

    out = writer_agent.run(
        job_id="WriterRewrite1234",
        ctx={
            "template_cfg": {
                "writer_format": ["Objective", "Discussion"],
                "quality": {"min_source_tags_per_section": 0},
            },
            "goal": "Revise only discussion.",
            "theory_text": "Theory",
            "research_facts": {},
            "data_summary": {},
            "data_highlights": {},
            "source_chunks": [{"id": "S2", "text": "Discussion source chunk."}],
            "extra_instructions": "Fix quality issues.",
            "rewrite_targets": ["Discussion"],
            "existing_sections": {
                "Objective": "Keep objective unchanged [S1]",
                "Discussion": "Old discussion",
            },
        },
    )

    assert out.ok is True
    assert called_sections == ["Discussion"]
    assert out.payload["sections"]["Objective"] == "Keep objective unchanged [S1]"
    assert out.payload["sections"]["Discussion"] == "Updated discussion body [S2]"
