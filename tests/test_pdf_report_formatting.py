"""Tests for test pdf report formatting."""

from __future__ import annotations

import base64
from pathlib import Path

from pypdf import PdfReader

from utils.pdf_report import (
    _is_md_table_row,
    _is_md_separator_row,
    _parse_md_row,
    _is_header_line,
    _group_images_by_section,
    build_submission_pdf,
    normalize_print_profile,
    get_print_profile_options,
)


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+o2kAAAAASUVORK5CYII="
)


def test_markdown_table_detection_helpers():
    assert _is_md_table_row("| a | b |")
    assert _is_md_separator_row("|---|:---:|")
    assert _parse_md_row("| a | b |") == ["a", "b"]


def test_header_line_detection():
    assert _is_header_line("Results:")
    assert _is_header_line("Apparatus & Procedure:")
    assert not _is_header_line("this is a normal sentence")


def test_group_images_by_section_uses_target_then_suggestions():
    headers = ["Objective", "Results", "Discussion"]
    grouped, remainder = _group_images_by_section(
        [
            {"target_section": "Results"},
            {"target_section": "", "suggested_sections": ["Discussion"]},
            {"target_section": "Nope", "suggested_sections": ["also_nope"]},
        ],
        headers,
    )
    assert len(grouped["Results"]) == 1
    assert len(grouped["Discussion"]) == 1
    assert len(remainder) == 1


def test_build_submission_pdf_places_targeted_images_within_section(tmp_path):
    image_path = tmp_path / "setup.png"
    image_path.write_bytes(_PNG_1X1)
    out_path = tmp_path / "out.pdf"

    build_submission_pdf(
        out_path=str(out_path),
        meta={
            "title": "Test Report",
            "template": "Lab / Technical Report",
            "name": "Student",
            "course": "Course",
            "group": "",
            "date": "2026-02-28",
        },
        source_summary="Summary",
        report_text=(
            "Objective:\n"
            "Test objective details.\n\n"
            "Results:\n"
            "Observed values are stable and repeatable."
        ),
        review_text="",
        data_preview=[],
        plot_paths={},
        uploaded_images=[
            {
                "label": "Image 1",
                "filename": "setup.png",
                "path": str(image_path),
                "title": "Setup photo",
                "caption": "Apparatus at t=0.",
                "target_section": "Results",
                "suggested_sections": [],
            }
        ],
        report_headers=["Objective", "Results"],
    )

    assert Path(out_path).exists()
    text = "\n".join([(p.extract_text() or "") for p in PdfReader(str(out_path)).pages])
    results_idx = text.find("Results")
    fig_idx = text.find("Figure 1. Setup photo")
    assert results_idx != -1
    assert fig_idx != -1
    assert fig_idx > results_idx
    assert "Uploaded Images" not in text


def test_print_profile_helpers():
    assert normalize_print_profile("DENSE") == "dense"
    assert normalize_print_profile("unknown") == "standard"
    opts = get_print_profile_options()
    assert any(o["key"] == "presentation" for o in opts)
