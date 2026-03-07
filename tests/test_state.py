"""Tests for test state."""

from __future__ import annotations

from utils.state import new_state, write_state, read_state


def test_read_state_returns_none_for_corrupt_file(tmp_path):
    jdir = tmp_path / "job1"
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / "state.json").write_text("{not json", encoding="utf-8")

    assert read_state(jdir) is None


def test_write_and_read_state_round_trip(tmp_path):
    jdir = tmp_path / "job2"
    jdir.mkdir(parents=True, exist_ok=True)

    st = new_state("JobABC1234")
    st.status = "running"
    st.stage = "writer"
    write_state(jdir, st)

    loaded = read_state(jdir)
    assert loaded is not None
    assert loaded.job_id == "JobABC1234"
    assert loaded.status == "running"
    assert loaded.stage == "writer"
