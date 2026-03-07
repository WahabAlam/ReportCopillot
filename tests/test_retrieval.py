"""Tests for test retrieval."""

from __future__ import annotations

from utils.retrieval import build_source_chunks, select_relevant_chunks, extract_source_tags


def test_build_source_chunks_assigns_sequential_ids():
    text = "\n\n".join([f"Paragraph {i} about mechanics and energy transfer." for i in range(1, 10)])
    chunks = build_source_chunks(text, chunk_chars=120, overlap_chars=20)
    assert len(chunks) >= 2
    assert chunks[0]["id"] == "S1"
    assert chunks[1]["id"] == "S2"
    assert all((c.get("text") or "").strip() for c in chunks)


def test_select_relevant_chunks_prefers_query_overlap():
    chunks = [
        {"id": "S1", "text": "Thermodynamics focuses on heat transfer and entropy."},
        {"id": "S2", "text": "Digital logic introduces gates, truth tables, and flip-flops."},
        {"id": "S3", "text": "Laplace transforms are useful for control systems."},
    ]
    top = select_relevant_chunks("heat transfer entropy", chunks, top_k=1)
    assert len(top) == 1
    assert top[0]["id"] == "S1"


def test_extract_source_tags_returns_sorted_unique_ids():
    text = "Result uses [S3], then [S1], then [S3] again."
    assert extract_source_tags(text) == ["S1", "S3"]
