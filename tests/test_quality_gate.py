from __future__ import annotations

from utils.quality_gate import evaluate_report_quality, build_quality_fix_prompt


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
