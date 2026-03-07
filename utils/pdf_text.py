"""Utility helpers for pdf text."""

from __future__ import annotations

from pypdf import PdfReader


def pdf_to_text(pdf_path: str, max_pages: int | None = None) -> str:
    reader = PdfReader(pdf_path)
    parts = []
    pages = reader.pages if not max_pages or max_pages < 1 else reader.pages[:max_pages]
    for p in pages:
        try:
            t = (p.extract_text() or "").strip()
        except Exception:
            # Skip problematic pages instead of failing whole extraction.
            continue
        if t:
            parts.append(t)
    return "\n\n".join(parts).strip()
