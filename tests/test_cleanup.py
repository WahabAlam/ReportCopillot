from __future__ import annotations

from pathlib import Path
from time import time

from utils.cleanup import cleanup_artifacts


def test_cleanup_dry_run_reports_without_deleting(tmp_path):
    outputs = tmp_path / "outputs"
    uploads = tmp_path / "uploads"
    outputs.mkdir()
    uploads.mkdir()

    old_file = outputs / "old.txt"
    old_file.write_text("old", encoding="utf-8")
    now = time()
    old_ts = now - (10 * 3600)
    old_file.touch()
    old_file.chmod(0o644)
    # force older mtime
    import os
    os.utime(old_file, (old_ts, old_ts))

    out = cleanup_artifacts(
        outputs_dir=str(outputs),
        uploads_dir=str(uploads),
        max_age_hours=1,
        dry_run=True,
    )
    assert out["deleted"] >= 1
    assert old_file.exists()


def test_cleanup_deletes_old_paths(tmp_path):
    outputs = tmp_path / "outputs"
    uploads = tmp_path / "uploads"
    outputs.mkdir()
    uploads.mkdir()

    old_dir = outputs / "job123"
    old_dir.mkdir()
    f = old_dir / "state.json"
    f.write_text("{}", encoding="utf-8")
    now = time()
    old_ts = now - (10 * 3600)
    import os
    os.utime(old_dir, (old_ts, old_ts))
    os.utime(f, (old_ts, old_ts))

    out = cleanup_artifacts(
        outputs_dir=str(outputs),
        uploads_dir=str(uploads),
        max_age_hours=1,
        dry_run=False,
    )
    assert out["deleted"] >= 1
    assert not old_dir.exists()
