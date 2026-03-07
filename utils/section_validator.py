"""Utility helpers for section validator."""

from __future__ import annotations

from typing import List


def find_missing_headers(report_text: str, required_headers: List[str]) -> List[str]:
    """
    Returns headers from required_headers that are not found in the report_text.

    We consider a header "present" if there's a line like:
      Header:
    (case-insensitive, allows extra spaces)

    Example: "Objective:" or "Objective:   "
    """
    text = report_text or ""
    present: set[str] = set()
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln.endswith(":"):
            continue
        present.add(ln[:-1].strip().lower())

    missing: List[str] = []
    for h in required_headers:
        if h.strip().lower() not in present:
            missing.append(h)
    return missing
