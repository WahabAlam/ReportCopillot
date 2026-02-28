# agents/data_agent.py
from __future__ import annotations

import pandas as pd
from schemas import AgentResult


def _safe_float(v):
    try:
        if pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def _detect_time_column(columns: list[str]) -> str | None:
    lower = {c.lower(): c for c in columns}
    candidates = ["time", "t", "time_s", "time_sec", "seconds", "timestamp"]
    for c in candidates:
        if c in lower:
            return lower[c]
    for c in columns:
        if c.lower().startswith("time"):
            return c
    return None


def _iqr_outlier_count(s: pd.Series) -> int:
    s = s.dropna()
    if s.empty:
        return 0
    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    if pd.isna(iqr) or iqr == 0:
        return 0
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    return int(((s < lo) | (s > hi)).sum())


def _linear_trend(df: pd.DataFrame, x_col: str, y_col: str) -> dict:
    pair = df[[x_col, y_col]].dropna()
    if len(pair) < 2:
        return {}
    x = pair[x_col].astype(float)
    y = pair[y_col].astype(float)
    x_mean = x.mean()
    y_mean = y.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom == 0:
        return {}
    slope = ((x - x_mean) * (y - y_mean)).sum() / denom
    intercept = y_mean - slope * x_mean
    y_pred = slope * x + intercept
    ss_tot = ((y - y_mean) ** 2).sum()
    ss_res = ((y - y_pred) ** 2).sum()
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot != 0 else None
    return {
        "x": x_col,
        "y": y_col,
        "n_used": int(len(pair)),
        "slope": _safe_float(slope),
        "intercept": _safe_float(intercept),
        "r2": _safe_float(r2),
    }


def _build_data_highlights(out: dict) -> dict:
    auto = out.get("auto_analysis") or {}
    key_findings: list[str] = []
    calculations: list[str] = []

    n_total = out.get("n_total")
    columns = out.get("columns") or []
    numeric_columns = out.get("numeric_columns") or []
    if n_total is not None:
        key_findings.append(
            f"Dataset has {int(n_total)} rows across {len(columns)} columns ({len(numeric_columns)} numeric)."
        )

    missingness = auto.get("missingness") or {}
    cols_with_missing = [
        (c, stats.get("missing_pct", 0.0))
        for c, stats in missingness.items()
        if float(stats.get("missing_count", 0) or 0) > 0
    ]
    cols_with_missing.sort(key=lambda x: x[1], reverse=True)
    if cols_with_missing:
        top_col, top_pct = cols_with_missing[0]
        key_findings.append(f"Highest missingness is in '{top_col}' ({top_pct:.1f}%).")

    trend = auto.get("primary_trend") or {}
    slope = trend.get("slope")
    r2 = trend.get("r2")
    if slope is not None:
        x = trend.get("x", "x")
        y = trend.get("y", "y")
        key_findings.append(f"Primary linear trend suggests '{y}' changes by {slope:.4g} per 1 unit of '{x}'.")
        if r2 is not None:
            calculations.append(
                f"Linear fit on ({x}, {y}): slope={slope:.6g}, intercept={trend.get('intercept')}, R^2={r2:.4f}"
            )

    top_correlations = auto.get("top_correlations") or []
    if top_correlations:
        c0 = top_correlations[0]
        pair = c0.get("pair") or ["col_a", "col_b"]
        corr = c0.get("corr")
        if corr is not None:
            key_findings.append(
                f"Strongest observed correlation is between '{pair[0]}' and '{pair[1]}' (r={corr:.3f})."
            )
            calculations.append(f"Pearson correlation: r({pair[0]}, {pair[1]}) = {corr:.6g}")

    outliers = auto.get("outliers_iqr_count") or {}
    if outliers:
        col, count = max(outliers.items(), key=lambda kv: kv[1])
        if int(count) > 0:
            key_findings.append(f"Most IQR outliers occur in '{col}' ({int(count)} points).")

    return {
        "key_findings": key_findings,
        "calculation_snippets": calculations,
    }


def run(*, job_id: str, ctx: dict) -> AgentResult:
    try:
        csv_path = ctx.get("csv_path")
        preview_rows = int(ctx.get("preview_rows", 10))

        if not csv_path:
            return AgentResult.success("data", job_id, payload={"data_summary": {}})

        df = pd.read_csv(csv_path)
        numeric_columns = list(df.select_dtypes(include="number").columns)
        all_columns = list(df.columns)

        out = {
            "n_total": int(df.shape[0]),
            "preview_rows": int(preview_rows),
            "columns": all_columns,
            "numeric_columns": numeric_columns,
            "describe_full": df.describe(include="all").to_dict(),
            "preview_head": df.head(preview_rows).to_dict(orient="records"),
            "auto_analysis": {},
        }

        missing_by_column = {}
        for col in all_columns:
            miss = int(df[col].isna().sum())
            missing_by_column[col] = {
                "missing_count": miss,
                "missing_pct": _safe_float((miss / len(df)) * 100.0) if len(df) else 0.0,
            }
        out["auto_analysis"]["missingness"] = missing_by_column

        if numeric_columns:
            numeric_summary = {}
            outliers = {}
            for col in numeric_columns:
                s = df[col]
                numeric_summary[col] = {
                    "min": _safe_float(s.min()),
                    "max": _safe_float(s.max()),
                    "mean": _safe_float(s.mean()),
                    "median": _safe_float(s.median()),
                    "std": _safe_float(s.std()),
                }
                outliers[col] = _iqr_outlier_count(s)
            out["auto_analysis"]["numeric_summary"] = numeric_summary
            out["auto_analysis"]["outliers_iqr_count"] = outliers

        time_col = _detect_time_column(all_columns)
        if time_col and numeric_columns:
            y_candidates = [c for c in numeric_columns if c != time_col]
            if y_candidates:
                out["auto_analysis"]["primary_trend"] = _linear_trend(df, time_col, y_candidates[0])

        if len(numeric_columns) >= 2:
            out["auto_analysis"]["numeric_candidates"] = numeric_columns
            corr = df[numeric_columns].corr(numeric_only=True)
            pairs = []
            for i, a in enumerate(numeric_columns):
                for b in numeric_columns[i + 1 :]:
                    v = corr.loc[a, b]
                    if pd.notna(v):
                        pairs.append({"pair": [a, b], "corr": float(v)})
            pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)
            out["auto_analysis"]["top_correlations"] = pairs[:5]

        data_highlights = _build_data_highlights(out)
        return AgentResult.success(
            "data",
            job_id,
            payload={"data_summary": out, "data_highlights": data_highlights},
        )
    except Exception as e:
        return AgentResult.fail("data", job_id, "Data agent failed", f"{type(e).__name__}: {e}")
