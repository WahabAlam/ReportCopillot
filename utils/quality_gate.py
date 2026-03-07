"""Utility helpers for quality gate."""

from __future__ import annotations

import re
from typing import Any

from utils.sections import split_by_headers
from utils.section_validator import find_missing_headers


def _word_count(text: str) -> int:
    return len([w for w in (text or "").split() if w.strip()])


def _extract_source_tags(text: str) -> list[str]:
    ids = {int(m.group(1)) for m in re.finditer(r"\[S(\d+)\]", text or "")}
    return [f"S{i}" for i in sorted(ids)]


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

    min_source_cfg = quality_cfg.get("min_source_tags_per_section", 0)
    default_min = 0
    per_section_min: dict[str, int] = {}
    if isinstance(min_source_cfg, int):
        default_min = max(0, int(min_source_cfg))
    elif isinstance(min_source_cfg, dict):
        for sec, n in min_source_cfg.items():
            try:
                per_section_min[str(sec)] = max(0, int(n))
            except Exception:
                continue

    if default_min > 0 or per_section_min:
        checks = required_headers if required_headers else list(sections.keys())
        for sec in checks:
            body = (sections.get(sec) or "").strip()
            if not body:
                continue
            min_required = per_section_min.get(sec, default_min)
            if min_required <= 0:
                continue
            tags = _extract_source_tags(body)
            if len(tags) < min_required:
                issues.append(
                    {
                        "kind": "missing_source_tags",
                        "section": sec,
                        "detail": (
                            f"Section '{sec}' should cite at least {min_required} source tag(s) "
                            f"like [S#] (found {len(tags)})."
                        ),
                    }
                )

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
        "- When source chunks are available, cite factual claims with [S#] tags.\n"
        "- Improve only the sections needed to resolve these quality issues:\n"
        f"{bullets}\n"
    )
