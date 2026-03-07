"""Tests for test quality gate."""

from __future__ import annotations

from utils.quality_gate import (
    evaluate_report_quality,
    build_quality_fix_prompt,
    select_quality_fix_sections,
)


def test_quality_gate_detects_missing_required_term():
    template_cfg = {
        "writer_format": ["Results", "Discussion"],
        "quality": {
            "required_terms_by_section": {"Discussion": ["limitation"]},
            "min_words": {"Results": 2},
        },
    }
    report = "Results:\nGood data summary.\n\nDiscussion:\nThis section is present but lacks expected wording."
    out = evaluate_report_quality(report, template_cfg)
    assert out["ok"] is False
    assert any(i["kind"] == "missing_term" for i in out["issues"])


def test_quality_fix_prompt_contains_issues():
    issues = [
        {"detail": "Section 'Discussion' is too short."},
        {"detail": "Report should mention: dataset"},
    ]
    p = build_quality_fix_prompt(issues, {"writer_format": ["Results", "Discussion"]})
    assert "IMPORTANT QUALITY FIX PASS" in p
    assert "Discussion" in p


def test_quality_gate_detects_missing_source_tags_when_configured():
    template_cfg = {
        "writer_format": ["Results"],
        "quality": {"min_source_tags_per_section": 1},
    }
    report = "Results:\nObserved trend increases over time."
    out = evaluate_report_quality(report, template_cfg)
    assert out["ok"] is False
    assert any(i["kind"] == "missing_source_tags" for i in out["issues"])


def test_quality_gate_accepts_section_with_source_tags():
    template_cfg = {
        "writer_format": ["Results"],
        "quality": {"min_source_tags_per_section": 1},
    }
    report = "Results:\nObserved trend increases over time. [S2]"
    out = evaluate_report_quality(report, template_cfg)
    assert out["ok"] is True


def test_select_quality_fix_sections_prefers_explicit_sections():
    issues = [
        {"kind": "too_short", "section": "Discussion", "detail": "short"},
        {"kind": "missing_term", "section": "Results", "detail": "missing term"},
    ]
    headers = ["Objective", "Results", "Discussion", "Conclusion"]
    out = select_quality_fix_sections(issues, headers)
    assert out == ["Results", "Discussion"]


def test_select_quality_fix_sections_handles_global_issue():
    issues = [{"kind": "missing_global_term", "section": "*", "detail": "trend"}]
    headers = ["Objective", "Results", "Discussion"]
    out = select_quality_fix_sections(issues, headers)
    assert out == ["Results"]
