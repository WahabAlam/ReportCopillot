from __future__ import annotations

from io import BytesIO
from pathlib import Path
import pytest

import utils.files as files


class DummyUpload:
    def __init__(self, filename: str, payload: bytes):
        self.filename = filename
        self.file = BytesIO(payload)


def test_save_upload_sanitizes_and_writes_unique_name(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(files, "UPLOAD_DIR", upload_dir)

    up = DummyUpload("../../bad name.csv", b"a,b\n1,2\n")
    path = files.save_upload(up, allowed_extensions={".csv"})
    p = Path(path)

    assert p.exists()
    assert p.parent == upload_dir
    assert ".." not in p.name
    assert " " not in p.name
    assert p.suffix == ".csv"


def test_save_upload_rejects_extension(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(files, "UPLOAD_DIR", upload_dir)

    up = DummyUpload("notes.txt", b"hello")
    with pytest.raises(ValueError, match="Invalid file type"):
        files.save_upload(up, allowed_extensions={".csv"})


def test_save_upload_rejects_large_file(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(files, "UPLOAD_DIR", upload_dir)

    up = DummyUpload("data.csv", b"x" * 11)
    with pytest.raises(ValueError, match="File too large"):
        files.save_upload(up, allowed_extensions={".csv"}, max_bytes=10)
