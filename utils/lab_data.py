"""Utility helpers for ingesting lab tabular data from multiple formats."""

from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import secrets

import pandas as pd

from utils.files import UPLOAD_DIR

TABULAR_FILE_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".json"}


def _ensure_frame(df: pd.DataFrame | pd.Series) -> pd.DataFrame:
    if isinstance(df, pd.Series):
        df = df.to_frame()
    if not isinstance(df, pd.DataFrame):
        raise ValueError("Parsed data is not tabular.")
    out = df.copy()
    out.columns = [str(c) for c in out.columns]
    return out


def _read_json_table(path: str) -> pd.DataFrame:
    # Try common JSON table shapes in order: records, line-delimited records, dict/list payloads.
    try:
        return _ensure_frame(pd.read_json(path, orient="records"))
    except Exception:
        pass

    try:
        return _ensure_frame(pd.read_json(path, lines=True))
    except Exception:
        pass

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Invalid JSON file: {type(e).__name__}: {e}") from e

    if isinstance(payload, list):
        return _ensure_frame(pd.DataFrame(payload))
    if isinstance(payload, dict):
        # Prefer records key if present; otherwise let pandas infer dict-of-lists/single-record.
        if isinstance(payload.get("records"), list):
            return _ensure_frame(pd.DataFrame(payload["records"]))
        return _ensure_frame(pd.DataFrame(payload))
    raise ValueError("Unsupported JSON table shape. Expected object or array.")


def read_tabular_file(path: str) -> pd.DataFrame:
    ext = Path(path).suffix.lower()
    if ext == ".csv":
        return _ensure_frame(pd.read_csv(path))
    if ext == ".tsv":
        return _ensure_frame(pd.read_csv(path, sep="\t"))
    if ext in {".xlsx", ".xls"}:
        return _ensure_frame(pd.read_excel(path))
    if ext == ".json":
        return _read_json_table(path)
    allowed = ", ".join(sorted(TABULAR_FILE_EXTENSIONS))
    raise ValueError(f"Unsupported tabular file type '{ext or '(none)'}'. Allowed: {allowed}")


def _looks_like_markdown_table(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    first = lines[0].strip()
    second = lines[1].strip().replace(" ", "")
    if not (first.startswith("|") and first.endswith("|")):
        return False
    if not (second.startswith("|") and second.endswith("|")):
        return False
    cells = [c for c in second.strip("|").split("|")]
    if not cells:
        return False
    for c in cells:
        if not c or set(c) - set("-:"):
            return False
    return True


def parse_table_text(table_text: str) -> pd.DataFrame:
    text = (table_text or "").strip()
    if not text:
        raise ValueError("Table text is empty.")
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError("Table text must include a header and at least one data row.")

    if _looks_like_markdown_table(lines):
        rows: list[list[str]] = []
        for raw in lines:
            line = raw.strip()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not cells:
                continue
            # Skip markdown separator row like |---|:---:|
            if all(c and not (set(c) - set("-:")) for c in cells):
                continue
            rows.append(cells)
        if len(rows) < 2:
            raise ValueError("Markdown table must include at least one data row.")
        width = max(len(r) for r in rows)
        norm = [r + [""] * (width - len(r)) for r in rows]
        header = [str(h).strip() or f"col_{idx + 1}" for idx, h in enumerate(norm[0])]
        return _ensure_frame(pd.DataFrame(norm[1:], columns=header))

    sample = lines[0]
    if "\t" in sample:
        sep = "\t"
    elif ";" in sample and "," not in sample:
        sep = ";"
    else:
        sep = ","
    return _ensure_frame(pd.read_csv(StringIO(text), sep=sep))


def save_table_text_as_csv(table_text: str) -> str:
    df = parse_table_text(table_text)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{secrets.token_hex(8)}_table_data.csv"
    df.to_csv(path, index=False)
    return str(path)
