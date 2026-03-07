"""Tests for lab data ingestion helpers."""

from __future__ import annotations

from utils.lab_data import read_tabular_file, parse_table_text


def test_read_tabular_file_supports_tsv(tmp_path):
    p = tmp_path / "data.tsv"
    p.write_text("time\ttemp\n0\t20\n1\t22\n", encoding="utf-8")

    df = read_tabular_file(str(p))
    assert list(df.columns) == ["time", "temp"]
    assert int(df.shape[0]) == 2


def test_read_tabular_file_supports_json_records(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('[{"time": 0, "value": 10.1}, {"time": 1, "value": 10.7}]', encoding="utf-8")

    df = read_tabular_file(str(p))
    assert "time" in df.columns
    assert "value" in df.columns
    assert int(df.shape[0]) == 2


def test_parse_table_text_supports_markdown_table():
    text = (
        "| time | temp |\n"
        "|---|---|\n"
        "| 0 | 20 |\n"
        "| 1 | 22 |\n"
    )
    df = parse_table_text(text)
    assert list(df.columns) == ["time", "temp"]
    assert int(df.shape[0]) == 2
