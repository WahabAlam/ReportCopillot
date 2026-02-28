from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from time import time
import shutil


@dataclass
class CleanupResult:
    max_age_hours: int
    dry_run: bool
    scanned: int = 0
    deleted: int = 0
    freed_bytes: int = 0
    deleted_paths: list[str] | None = None

    def to_dict(self) -> dict:
        out = asdict(self)
        if out["deleted_paths"] is None:
            out["deleted_paths"] = []
        return out


def _is_old(path: Path, cutoff_ts: float) -> bool:
    return path.stat().st_mtime < cutoff_ts


def _bytes_for_path(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def cleanup_artifacts(
    *,
    outputs_dir: str = "outputs",
    uploads_dir: str = "uploads",
    max_age_hours: int = 24 * 7,
    dry_run: bool = True,
    max_paths_reported: int = 100,
) -> dict:
    cutoff_ts = time() - (max_age_hours * 3600)
    res = CleanupResult(max_age_hours=max_age_hours, dry_run=dry_run, deleted_paths=[])

    for root in (Path(outputs_dir), Path(uploads_dir)):
        if not root.exists():
            continue
        for path in root.iterdir():
            res.scanned += 1
            try:
                if not _is_old(path, cutoff_ts):
                    continue
                size = _bytes_for_path(path)
                if not dry_run:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                res.deleted += 1
                res.freed_bytes += size
                if len(res.deleted_paths) < max_paths_reported:
                    res.deleted_paths.append(str(path))
            except Exception:
                # Best-effort cleanup; skip unreadable paths.
                continue

    return res.to_dict()
