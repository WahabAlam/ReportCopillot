"""Utility helpers for lexical source chunking and retrieval."""

from __future__ import annotations

import re
from collections import Counter

# Small stopword set is enough for lightweight lexical ranking.
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_SOURCE_TAG_RE = re.compile(r"\[S(\d+)\]")


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if len(raw) <= 1 or raw in _STOPWORDS:
            continue
        out.append(raw)
    return out


def build_source_chunks(
    text: str,
    *,
    chunk_chars: int = 1200,
    overlap_chars: int = 160,
) -> list[dict]:
    """Split long manual text into stable [S#] chunks for grounding/citation."""
    raw = re.sub(r"\r\n?", "\n", text or "").strip()
    if not raw:
        return []

    chunk_chars = max(300, int(chunk_chars))
    overlap_chars = max(0, min(int(overlap_chars), chunk_chars // 2))

    chunks: list[dict] = []
    start = 0
    n = len(raw)
    while start < n:
        end = min(n, start + chunk_chars)
        if end < n:
            pivot = start + int(chunk_chars * 0.6)
            cut = raw.rfind("\n\n", pivot, end)
            if cut == -1:
                cut = raw.rfind("\n", pivot, end)
            if cut > start + 80:
                end = cut

        body = raw[start:end].strip()
        if body:
            chunks.append({"id": f"S{len(chunks) + 1}", "text": body})
        if end >= n:
            break
        start = max(0, end - overlap_chars)

    # Drop accidental duplicates from overlap boundaries.
    deduped: list[dict] = []
    prev = ""
    for chunk in chunks:
        body = chunk.get("text", "")
        if body and body != prev:
            deduped.append({"id": f"S{len(deduped) + 1}", "text": body})
            prev = body
    return deduped


def select_relevant_chunks(query: str, source_chunks: list[dict], *, top_k: int = 6) -> list[dict]:
    """Return top lexical matches for a section/query prompt."""
    chunks = [c for c in (source_chunks or []) if isinstance(c, dict) and (c.get("text") or "").strip()]
    if not chunks:
        return []

    top_k = max(1, int(top_k))
    q_tokens = Counter(_tokenize(query))
    if not q_tokens:
        return chunks[:top_k]

    scored: list[tuple[float, int, dict]] = []
    for idx, chunk in enumerate(chunks):
        c_tokens = _tokenize(chunk.get("text", ""))
        if not c_tokens:
            continue
        c_counts = Counter(c_tokens)
        overlap = sum(min(q_tokens[t], c_counts[t]) for t in q_tokens if t in c_counts)
        if overlap <= 0:
            continue
        # Light length normalization to avoid always favoring very long chunks.
        norm = overlap / max(1.0, (len(c_tokens) ** 0.5))
        score = float(overlap) + norm
        scored.append((score, idx, chunk))

    if not scored:
        return chunks[:top_k]

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, _, c in scored[:top_k]]


def extract_source_tags(text: str) -> list[str]:
    """Extract unique [S#] tags sorted by numeric id."""
    ids = {int(m.group(1)) for m in _SOURCE_TAG_RE.finditer(text or "")}
    return [f"S{i}" for i in sorted(ids)]

