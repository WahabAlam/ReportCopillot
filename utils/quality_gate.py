from __future__ import annotations

from typing import Any

from utils.sections import split_by_headers
from utils.section_validator import find_missing_headers


def _word_count(text: str) -> int:
    return len([w for w in (text or "").split() if w.strip()])


def evaluate_report_quality(report_text: str, template_cfg: dict | None) -> dict[str, Any]:
    template_cfg = template_cfg or {}
    quality_cfg = template_cfg.get("quality", {}) or {}
    required_headers = template_cfg.get("writer_format", []) or []
    sections = split_by_headers(report_text, required_headers) if required_headers else {}

    issues: list[dict[str, str]] = []

    missing_headers = find_missing_headers(report_text, required_headers) if required_headers else []
    for h in missing_headers:
        issues.append({"kind": "missing_header", "section": h, "detail": f"Missing required header: {h}:"})

    min_words = quality_cfg.get("min_words", {}) or {}
    for sec, min_n in min_words.items():
        body = (sections.get(sec) or "").strip()
        if body and _word_count(body) < int(min_n):
            issues.append(
                {
                    "kind": "too_short",
                    "section": sec,
                    "detail": f"Section '{sec}' is too short ({_word_count(body)} words, expected >= {int(min_n)}).",
                }
            )

    required_terms_by_section = quality_cfg.get("required_terms_by_section", {}) or {}
    for sec, terms in required_terms_by_section.items():
        body = (sections.get(sec) or "").lower()
        if not body:
            continue
        terms = [str(t).lower() for t in (terms or [])]
        if terms and not any(t in body for t in terms):
            issues.append(
                {
                    "kind": "missing_term",
                    "section": sec,
                    "detail": f"Section '{sec}' should mention at least one of: {', '.join(terms)}.",
                }
            )

    required_global_terms = [str(t).lower() for t in (quality_cfg.get("required_global_terms", []) or [])]
    text_l = (report_text or "").lower()
    for t in required_global_terms:
        if t not in text_l:
            issues.append({"kind": "missing_global_term", "section": "*", "detail": f"Report should mention: {t}"})

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "sections": sections,
    }


def build_quality_fix_prompt(issues: list[dict[str, str]], template_cfg: dict | None) -> str:
    template_cfg = template_cfg or {}
    required = template_cfg.get("writer_format", []) or []
    required_list = ", ".join([f"{h}:" for h in required]) if required else "(template-defined headers)"
    bullets = "\n".join([f"- {i.get('detail', '')}" for i in issues[:12]])
    return (
        "IMPORTANT QUALITY FIX PASS:\n"
        "- Revise and return the FULL report.\n"
        f"- Keep and preserve exact required headers: {required_list}\n"
        "- Do not invent facts or measurements.\n"
        "- Improve only the sections needed to resolve these quality issues:\n"
        f"{bullets}\n"
    )
