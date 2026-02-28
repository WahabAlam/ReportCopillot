from __future__ import annotations

from reportlab.lib.styles import getSampleStyleSheet

from utils.pdf_report import _is_md_table_row, _is_md_separator_row, _parse_md_row, _is_header_line


def test_markdown_table_detection_helpers():
    assert _is_md_table_row("| a | b |")
    assert _is_md_separator_row("|---|:---:|")
    assert _parse_md_row("| a | b |") == ["a", "b"]


def test_header_line_detection():
    assert _is_header_line("Results:")
    assert _is_header_line("Apparatus & Procedure:")
    assert not _is_header_line("this is a normal sentence")
