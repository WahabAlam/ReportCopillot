from __future__ import annotations

import orchestrator
from schemas import AgentResult


def test_retries_writer_when_required_headers_missing(monkeypatch):
    calls = {"writer": 0}

    def fake_research(*, job_id: str, ctx: dict):
        return AgentResult.success("research", job_id, payload={"theory_text": "theory"})

    def fake_data(*, job_id: str, ctx: dict):
        return AgentResult.success("data", job_id, payload={"data_summary": {"n_total": 3}})

    def fake_writer(*, job_id: str, ctx: dict):
        calls["writer"] += 1
        if calls["writer"] == 1:
            return AgentResult.success(
                "writer",
                job_id,
                payload={
                    "report_text": "Objective:\nx",
                    "sections": {"Objective": "x", "Conclusion": ""},
                },
            )
        return AgentResult.success(
            "writer",
            job_id,
            payload={
                "report_text": "Objective:\nx\n\nConclusion:\ny",
                "sections": {"Objective": "x", "Conclusion": "y"},
            },
        )

    def fake_reviewer(*, job_id: str, ctx: dict):
        return AgentResult.success("reviewer", job_id, payload={"review_text": "ok"})

    def fake_diagram(*, job_id: str, ctx: dict):
        return AgentResult.success("diagram", job_id, payload={"figures_text": "fig"})

    monkeypatch.setattr(orchestrator, "research_run", fake_research)
    monkeypatch.setattr(orchestrator, "data_run", fake_data)
    monkeypatch.setattr(orchestrator, "writer_run", fake_writer)
    monkeypatch.setattr(orchestrator, "reviewer_run", fake_reviewer)
    monkeypatch.setattr(orchestrator, "diagram_run", fake_diagram)

    out = orchestrator.run_pipeline(
        job_id="job12345",
        manual_text="manual",
        goal="goal",
        csv_path=None,
        extra_instructions="",
        template_cfg={"writer_format": ["Objective", "Conclusion"]},
        include_review=False,
    )

    assert calls["writer"] == 2
    assert out["report_sections"]["Conclusion"] == "y"
    assert "Conclusion:" in out["report"]


def test_does_not_retry_when_sections_present(monkeypatch):
    calls = {"writer": 0}

    monkeypatch.setattr(
        orchestrator,
        "research_run",
        lambda *, job_id, ctx: AgentResult.success("research", job_id, payload={"theory_text": "theory"}),
    )
    monkeypatch.setattr(
        orchestrator,
        "data_run",
        lambda *, job_id, ctx: AgentResult.success("data", job_id, payload={"data_summary": {}}),
    )

    def fake_writer(*, job_id: str, ctx: dict):
        calls["writer"] += 1
        return AgentResult.success(
            "writer",
            job_id,
            payload={
                "report_text": "Objective:\nA\n\nConclusion:\nB",
                "sections": {"Objective": "A", "Conclusion": "B"},
            },
        )

    monkeypatch.setattr(orchestrator, "writer_run", fake_writer)
    monkeypatch.setattr(
        orchestrator,
        "diagram_run",
        lambda *, job_id, ctx: AgentResult.success("diagram", job_id, payload={"figures_text": ""}),
    )

    out = orchestrator.run_pipeline(
        job_id="job12345",
        manual_text="manual",
        goal="goal",
        csv_path=None,
        extra_instructions="",
        template_cfg={"writer_format": ["Objective", "Conclusion"]},
        include_review=False,
    )

    assert calls["writer"] == 1
    assert out["report_sections"]["Objective"] == "A"


def test_passes_structured_research_and_data_highlights_to_writer(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "research_run",
        lambda *, job_id, ctx: AgentResult.success(
            "research",
            job_id,
            payload={"theory_text": "theory", "research_facts": {"key_concepts": ["x"]}},
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "data_run",
        lambda *, job_id, ctx: AgentResult.success(
            "data",
            job_id,
            payload={
                "data_summary": {"n_total": 3},
                "data_highlights": {"key_findings": ["k1"], "calculation_snippets": ["c1"]},
            },
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "diagram_run",
        lambda *, job_id, ctx: AgentResult.success("diagram", job_id, payload={"figures_text": ""}),
    )

    observed: dict = {}

    def fake_writer(*, job_id: str, ctx: dict):
        observed["research_facts"] = ctx.get("research_facts")
        observed["data_highlights"] = ctx.get("data_highlights")
        return AgentResult.success(
            "writer",
            job_id,
            payload={"report_text": "Objective:\nA", "sections": {"Objective": "A"}},
        )

    monkeypatch.setattr(orchestrator, "writer_run", fake_writer)

    out = orchestrator.run_pipeline(
        job_id="job_struct_123",
        manual_text="manual",
        goal="goal",
        csv_path=None,
        extra_instructions="",
        template_cfg={"writer_format": ["Objective"]},
        include_review=False,
    )

    assert observed["research_facts"] == {"key_concepts": ["x"]}
    assert observed["data_highlights"]["key_findings"] == ["k1"]
    assert out["research_facts"]["key_concepts"] == ["x"]
    assert out["data_highlights"]["calculation_snippets"] == ["c1"]
