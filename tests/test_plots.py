"""Tests for test plots."""

from __future__ import annotations

from pathlib import Path

from utils.plots import generate_plots


def test_generate_plots_accepts_numeric_like_columns(tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text(
        "time,temp\n"
        "0,20\n"
        "1,21.5\n"
        "2,23\n"
        "3,24.2\n",
        encoding="utf-8",
    )

    job_id = "PlotNumericLike1234"
    out = generate_plots(str(csv), job_id=job_id)
    assert out
    for p in out.values():
        assert Path(p).exists()
