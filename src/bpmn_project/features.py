"""Calendar-aware features and versioned labels computed without future predictors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .common import csv, json_out

BASE_FEATURES = [
    "wip",
    "wip_lag1",
    "wip_lag2",
    "wip_med6_past",
    "wip_ratio_med6",
    "wip_share",
    "share_med6_past",
    "wip_change1",
    "history_count",
    "gap_months",
]


def calendar_features(monthly, config):
    """Missing months stay missing, not zero; lag1 always means one calendar month.

    Rework/scrap are exported for audit, but excluded from primary prediction because
    reporting availability at prediction time is not established by this workbook.
    """
    if monthly.duplicated(["ym", "node"]).any():
        raise ValueError("Duplicate station-month observations")
    source = monthly[["ym", "node", "activity_id", "department", "wip", "rework", "scrap"]].copy()
    source["month"] = pd.PeriodIndex(source.ym, freq="M")
    if (source.wip < 0).any():
        raise ValueError("Negative WIP")
    totals = source.groupby("month").wip.sum(min_count=1)
    months = pd.period_range(source.month.min(), source.month.max(), freq="M")
    frames = []
    window, min_history = config["history_months"], config["min_history"]
    for node, group in source.groupby("node", sort=True):
        g = group.set_index("month").reindex(months)
        g.index.name = "month"
        g["node"] = node
        for col in ["activity_id", "department"]:
            g[col] = group[col].iloc[0]
        g["observed_month"] = g.wip.notna()
        g["ym"] = g.index.astype(str)
        g["wip_lag1"] = g.wip.shift(1)
        g["wip_lag2"] = g.wip.shift(2)
        history = g.wip.shift(1).rolling(window, min_periods=min_history)
        g["wip_med6_past"] = history.median()
        g["history_count"] = g.wip.shift(1).rolling(window, min_periods=1).count()
        g["wip_ratio_med6"] = g.wip / g.wip_med6_past.replace(0, np.nan)
        g["wip_share"] = g.wip / totals.reindex(g.index).replace(0, np.nan)
        g["share_med6_past"] = g.wip_share.shift(1).rolling(window, min_periods=min_history).median()
        g["wip_change1"] = g.wip - g.wip_lag1
        ordinal = pd.Series(np.arange(len(g)), index=g.index, dtype=float)
        last_observed = ordinal.where(g.observed_month).ffill().shift(1)
        g["gap_months"] = ordinal - last_observed
        # Labels are stored separately: these fields must never enter model features.
        g["wip_next"] = g.wip.shift(-1)
        g["ym_next"] = (g.index + 1).astype(str)
        g["surge_threshold"] = np.maximum(config["surge_min_wip"], config["surge_ratio"] * g.wip_med6_past)
        g["y_surge_next"] = (g.wip_next > g.surge_threshold).astype(int)
        g["persistence_surge"] = (g.wip > g.surge_threshold).astype(int)
        frames.append(g.reset_index())
    panel = pd.concat(frames, ignore_index=True).sort_values(["month", "node"]).reset_index(drop=True)
    # Exact top ceil(n*.20), stable ties resolved by node name. Cross-section is same-month only.
    ranks = panel.groupby("month").wip.rank(method="first", ascending=False)
    n = panel.groupby("month").wip.transform("count")
    panel["current_top20"] = (ranks <= np.ceil(config["top_fraction"] * n)).astype(int)
    next_ranks = panel.groupby("node", sort=False).current_top20.shift(-1)
    panel["y_top20_next"] = next_ranks
    panel["eligible"] = panel.observed_month & panel.wip_next.notna() & panel.wip_med6_past.notna()
    return panel


def build_features(ctx, sheets):
    out = ctx.directory("forecast")
    settings = ctx.config["experiment"]
    panel = calendar_features(sheets["D4 Dữ liệu trạm-tháng"], settings)
    csv(panel, out / "calendar_panel.csv")
    model_data = panel[panel.eligible].copy().reset_index(drop=True)
    model_data["y_top20_next"] = model_data.y_top20_next.astype(int)
    model_data["split"] = np.where(model_data.ym.ge(settings["test_start"]), "test", "train")
    csv(model_data, out / "model_dataset.csv")
    old = sheets["D4 Dữ liệu trạm-tháng"]
    comparisons = panel[panel.observed_month].merge(old, on=["ym", "node"], suffixes=("_new", "_excel"))
    differences = []
    for col in ["wip_lag1", "wip_lag2", "wip_med6_past", "wip_ratio_med6", "share_med6_past"]:
        a, b = comparisons[f"{col}_new"], comparisons[f"{col}_excel"]
        mask = ~np.isclose(a, b, equal_nan=True)
        for i in comparisons.index[mask]:
            differences.append(
                {
                    "ym": comparisons.loc[i, "ym"],
                    "node": comparisons.loc[i, "node"],
                    "feature": col,
                    "calendar_value": a.loc[i],
                    "excel_value": b.loc[i],
                }
            )
    csv(pd.DataFrame(differences), out / "excel_feature_differences.csv")
    label_compare = model_data.merge(
        sheets["D5 Nhãn ùn tháng sau"], on=["ym", "node"], suffixes=("_new", "_excel")
    )
    csv(
        label_compare[
            ["ym", "node", "y_top20_next_new", "y_top20_next_excel", "y_surge_next_new", "y_surge_next_excel"]
        ],
        out / "excel_label_comparison.csv",
    )
    json_out(
        {
            "target_version": "calendar_v1",
            "cutoff": "end of month t; WIP snapshot for t assumed available; predict t+1",
            "labels": {
                "y_top20_next": "rank WIP at t+1, descending; first ceil(20%*n) stations; node-name tie break",
                "y_surge_next": "WIP(t+1) > max(20, 1.5*median of observed WIP in calendar t-6..t-1); at least 3 months",
            },
            "feature_columns": BASE_FEATURES,
            "missing_policy": "reindex every month; calendar lags; missing months stay NaN; train-only median imputation + indicators",
            "excluded_predictors": [
                "wip_next",
                "y_*",
                "ym_next",
                "E* predictions",
                "current rework/scrap (availability unknown)",
            ],
            "n_samples": len(model_data),
            "n_stations": model_data.node.nunique(),
            "split_counts": model_data.groupby("split").size().to_dict(),
            "label_comparison": {
                label: int(label_compare[f"{label}_new"].ne(label_compare[f"{label}_excel"]).sum())
                for label in ["y_top20_next", "y_surge_next"]
            },
            "note": "Surge definition is newly specified and versioned; old D5 generation rule is unavailable. Scores are not directly comparable with E1.",
        },
        out / "feature_contract.json",
    )
    # Calendar gaps are explicit evidence, not silently compressed into adjacent months.
    csv(panel[~panel.observed_month][["ym", "node", "activity_id"]], out / "missing_calendar_months.csv")
    return panel, model_data
