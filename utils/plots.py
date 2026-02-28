# utils/plots.py

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


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


def generate_plots(csv_path: str, job_id: str) -> dict:
    """
    Returns {caption: png_path}. Never raises; returns {} on failure.
    """
    try:
        df = pd.read_csv(csv_path)
        cols = list(df.columns)

        time_col = _detect_time_column(cols)
        y_col = _first_numeric_non_time(df, time_col)

        if y_col is None:
            return {}

        saved: dict[str, str] = {}

        # 1) time series if time column exists
        if time_col:
            p = OUTPUT_DIR / f"{job_id}_fig1_time_series.png"
            plt.figure(figsize=(7, 4.2))
            plt.plot(df[time_col], df[y_col], marker="o")
            plt.xlabel(_pretty_label(time_col))
            plt.ylabel(_pretty_label(y_col))
            plt.title(f"{_pretty_label(y_col)} vs {_pretty_label(time_col)}")
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(p, dpi=300)
            plt.close()
            saved["Primary variable vs time"] = str(p)

        # 2) histogram
        p = OUTPUT_DIR / f"{job_id}_fig2_hist.png"
        plt.figure(figsize=(7, 4.2))
        plt.hist(df[y_col].dropna(), bins=10, edgecolor="black")
        plt.xlabel(_pretty_label(y_col))
        plt.ylabel("Count")
        plt.title(f"Distribution of {_pretty_label(y_col)}")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(p, dpi=300)
        plt.close()
        saved["Histogram of primary variable"] = str(p)

        # 3) box plot
        p = OUTPUT_DIR / f"{job_id}_fig3_box.png"
        plt.figure(figsize=(6.5, 4.2))
        plt.boxplot(df[y_col].dropna())
        plt.ylabel(_pretty_label(y_col))
        plt.xticks([1], [_pretty_label(y_col)])
        plt.title(f"Box Plot of {_pretty_label(y_col)}")
        plt.grid(True)
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
