from __future__ import annotations

from pathlib import Path
import re
import secrets

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def _clean_name(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        raise ValueError("Missing filename")
    # Keep only safe path characters and collapse to a predictable basename.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return cleaned[:120] or "upload"


def save_upload(
    file_obj,
    *,
    allowed_extensions: set[str] | None = None,
    max_bytes: int = 20 * 1024 * 1024,
) -> str:
    safe_name = _clean_name(getattr(file_obj, "filename", ""))
    ext = Path(safe_name).suffix.lower()

    if allowed_extensions is not None and ext not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ValueError(f"Invalid file type '{ext or '(none)'}'. Allowed: {allowed}")

    payload = file_obj.file.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"File too large (max {max_bytes // (1024 * 1024)} MB)")

    unique_name = f"{secrets.token_hex(8)}_{safe_name}"
    path = UPLOAD_DIR / unique_name
    path.write_bytes(payload)
    return str(path)
