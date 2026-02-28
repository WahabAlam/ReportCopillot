# utils/jobs.py
from __future__ import annotations

from pathlib import Path
import secrets
import json
from datetime import datetime, UTC

OUTPUT_DIR = Path("outputs").resolve()
OUTPUT_DIR.mkdir(exist_ok=True)


def new_job_id() -> str:
    raw = secrets.token_urlsafe(10)
    cleaned = "".join(ch for ch in raw if ch.isalnum())
    return cleaned[:24] if len(cleaned) >= 8 else (cleaned + "A1B2C3D4")[:12]


def job_pdf_path(job_id: str) -> Path:
    return OUTPUT_DIR / f"{job_id}.pdf"


def is_safe_job_id(job_id: str) -> bool:
    return job_id.isalnum() and (8 <= len(job_id) <= 32)


def job_dir(job_id: str) -> Path:
    d = OUTPUT_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_debug_path(job_id: str) -> Path:
    return job_dir(job_id) / "debug.json"


def job_text_path(job_id: str, name: str) -> Path:
    return job_dir(job_id) / name


def write_job_debug(job_id: str, data: dict) -> None:
    payload = {
        "job_id": job_id,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **data,
    }
    job_debug_path(job_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_job_debug(job_id: str) -> dict:
    p = job_debug_path(job_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def upsert_job_debug(job_id: str, data: dict) -> None:
    current = read_job_debug(job_id)
    current.update(data or {})
    payload = {
        "job_id": job_id,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **current,
    }
    job_debug_path(job_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_job_text(job_id: str, filename: str, text: str) -> None:
    job_text_path(job_id, filename).write_text(text or "", encoding="utf-8")


def read_job_text(job_id: str, filename: str) -> str:
    p = job_text_path(job_id, filename)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""
