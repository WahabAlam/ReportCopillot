"""Utility helpers for state."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path
import json
from typing import Literal, Optional

Status = Literal["queued", "running", "failed", "done", "canceled"]

def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")

@dataclass
class JobState:
    job_id: str
    status: Status
    created_at: str
    updated_at: str
    error: Optional[str] = None
    pdf_filename: Optional[str] = None
    debug_filename: Optional[str] = None
    stage: Optional[str] = None
    progress_pct: int = 0
    cancellation_requested: bool = False
    queue_mode: Optional[str] = None
    queue_job_id: Optional[str] = None

def state_path(job_dir: Path) -> Path:
    return job_dir / "state.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_state(job_dir: Path, state: JobState) -> None:
    state.updated_at = _utc_now()
    p = state_path(job_dir)
    _atomic_write_json(p, asdict(state))

def read_state(job_dir: Path) -> Optional[JobState]:
    p = state_path(job_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return JobState(**data)
    except Exception:
        return None

def new_state(job_id: str) -> JobState:
    now = _utc_now()
    return JobState(
        job_id=job_id,
        status="queued",
        created_at=now,
        updated_at=now,
        error=None,
        pdf_filename=f"{job_id}.pdf",
        debug_filename="debug.json",
        stage="queued",
        progress_pct=0,
        cancellation_requested=False,
        queue_mode=None,
        queue_job_id=None,
    )
