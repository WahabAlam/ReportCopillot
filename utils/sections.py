# utils/sections.py
from __future__ import annotations

from typing import Dict, List


def split_by_headers(report_text: str, headers: List[str]) -> Dict[str, str]:
    """
    Split a plain-text report into sections keyed by header name (without the colon).
    Only recognizes headers in the provided list, in plain-text form "Header:".
    """
    lines = (report_text or "").splitlines()
    header_set = set(h.strip() for h in (headers or []))

    current: str | None = None
    out_lines: Dict[str, List[str]] = {h: [] for h in headers}

    for ln in lines:
        stripped = ln.strip()

        # recognize a header line like "Objective:"
        if stripped.endswith(":"):
            name = stripped[:-1].strip()
            if name in header_set:
                current = name
                continue

        if current is not None:
            out_lines[current].append(ln)

    return {k: "\n".join(v).strip() for k, v in out_lines.items()}


def join_sections(sections: Dict[str, str], headers: List[str]) -> str:
    """
    Join a dict of sections back into plain-text report text with required headers.
    """
    parts: List[str] = []
    for h in (headers or []):
        parts.append(f"{h}:")
        parts.append((sections.get(h) or "").strip())
        parts.append("")  # blank line between sections
    return "\n".join(parts).strip()
