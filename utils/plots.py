"""Utility helpers for plots."""

# utils/plots.py

from __future__ import annotations

import os
from pathlib import Path
import pandas as pd
import matplotlib
from utils.lab_data import read_tabular_file

# Use a non-GUI backend to keep background worker and tests stable.
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


MAX_PLOT_POINTS = _env_int("MAX_PLOT_POINTS", 2000)


def _pretty_label(col: str) -> str:
    c = (col or "").strip()
    if not c:
        return c
    low = c.lower()
    if low.endswith("_c"):
        return f"{c[:-2].replace('_', ' ').title()} (C)"
    if low.endswith("_f"):
        return f"{c[:-2].replace('_', ' ').title()} (F)"
    if low.endswith("_s"):
        return f"{c[:-2].replace('_', ' ').title()} (s)"
    if low.endswith("_sec"):
        return f"{c[:-4].replace('_', ' ').title()} (s)"
    return c.replace("_", " ").title()


def _detect_time_column(cols: list[str]) -> str | None:
    candidates = ["time", "t", "time_s", "time_sec", "seconds", "timestamp"]
    lower = {c.lower(): c for c in cols}
    for k in candidates:
        if k in lower:
            return lower[k]
    for c in cols:
        if c.lower().startswith("time"):
            return c
    return None


def _first_numeric_non_time(df: pd.DataFrame, time_col: str | None) -> str | None:
    numeric_cols = list(df.select_dtypes(include="number").columns)
    if time_col and time_col in numeric_cols:
        numeric_cols.remove(time_col)
    return numeric_cols[0] if numeric_cols else None


def _first_numeric_like_non_time(df: pd.DataFrame, time_col: str | None) -> str | None:
    for col in df.columns:
        if time_col and col == time_col:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if int(s.notna().sum()) >= 2:
            return str(col)
    return None


def _downsample_pair(x: pd.Series, y: pd.Series, max_points: int) -> tuple[pd.Series, pd.Series]:
    if max_points <= 0 or len(x) <= max_points:
        return x, y
    step = max(1, len(x) // max_points)
    idx = slice(0, None, step)
    return x.iloc[idx], y.iloc[idx]


def generate_plots(csv_path: str, job_id: str) -> dict:
    """
    Returns {caption: png_path}. Never raises; returns {} on failure.
    """
    try:
        df = read_tabular_file(csv_path)
        if df.empty:
            return {}
        cols = list(df.columns)

        time_col = _detect_time_column(cols)
        y_col = _first_numeric_non_time(df, time_col)
        if y_col is None:
            y_col = _first_numeric_like_non_time(df, time_col)

        if y_col is None:
            return {}

        y_clean = pd.to_numeric(df[y_col], errors="coerce").dropna()
        if y_clean.empty:
            return {}

        saved: dict[str, str] = {}

        # 1) time series if time column exists
        if time_col:
            pair = pd.DataFrame({time_col: df[time_col], y_col: pd.to_numeric(df[y_col], errors="coerce")}).dropna()
            if len(pair) >= 2:
                x = pair[time_col]
                y = pair[y_col]
                x, y = _downsample_pair(x, y, MAX_PLOT_POINTS)
                p = OUTPUT_DIR / f"{job_id}_fig1_time_series.png"
                plt.figure(figsize=(7, 4.2))
                plt.plot(x, y, marker="o", linewidth=1.5, markersize=3)
                plt.xlabel(_pretty_label(time_col))
                plt.ylabel(_pretty_label(y_col))
                plt.title(f"{_pretty_label(y_col)} vs {_pretty_label(time_col)}")
                plt.grid(True, alpha=0.35)
                plt.tight_layout()
                plt.savefig(p, dpi=300)
                plt.close()
                saved["Primary variable vs time"] = str(p)

        # 2) histogram
        p = OUTPUT_DIR / f"{job_id}_fig2_hist.png"
        plt.figure(figsize=(7, 4.2))
        plt.hist(y_clean, bins=10, edgecolor="black")
        plt.xlabel(_pretty_label(y_col))
        plt.ylabel("Count")
        plt.title(f"Distribution of {_pretty_label(y_col)}")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(p, dpi=300)
        plt.close()
        saved["Histogram of primary variable"] = str(p)

        # 3) box plot
        p = OUTPUT_DIR / f"{job_id}_fig3_box.png"
        plt.figure(figsize=(6.5, 4.2))
        plt.boxplot(y_clean)
        plt.ylabel(_pretty_label(y_col))
        plt.xticks([1], [_pretty_label(y_col)])
        plt.title(f"Box Plot of {_pretty_label(y_col)}")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(p, dpi=300)
        plt.close()
        saved["Box plot of primary variable"] = str(p)

        return saved

    except Exception:
        try:
            plt.close("all")
        except Exception:
            pass
        return {}
