"""Descriptive measurements with explicit denominators and event-level traceability."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .common import csv, json_out, plot_setup, save_plot

PAINT = "Sơn lớp được chỉ định"
SAND = "Chà nhám lớp được chỉ định"


def business_stage(activity, department):
    """Assign QC to its inspected stage, following the supplied B0 convention."""
    for qc, stage in [
        ("QC0", "Chuẩn bị vật tư/Cắt"),
        ("QC1", "Tạo hình/Tách khuôn/Ổn định"),
        ("QC2", "CNC"),
        ("QC3", "Chà nhám"),
        ("QC4", "Chà nhám"),
        ("QC5", "Dán keo"),
        ("QC6", "Sơn"),
        ("QC7", "Đánh bóng"),
        ("QC8", "Vệ sinh/Lắp ráp/Đóng gói"),
    ]:
        if str(activity).startswith(qc):
            return stage
    if str(activity).startswith("Kiểm tra chất lượng cuối"):
        return "Vệ sinh/Lắp ráp/Đóng gói"
    if department == "Vận chuyển nội bộ":
        return "Vận chuyển/chờ chuyển"
    return department


def bottleneck_evidence(ctx, events, sheets):
    annotated = events.copy()
    annotated["stage"] = [business_stage(a, d) for a, d in zip(annotated.activity_mes, annotated.department)]
    annotated["defect"] = annotated.outcome.eq("FAIL - DEFECT")
    observed = (
        annotated.groupby("stage")
        .agg(
            sample_events=("event_id", "size"),
            sample_cases=("case_id", "nunique"),
            sample_defects=("defect", "sum"),
            sample_inter_scan_gap_hours=("gap_min", lambda s: s.sum() / 60),
            sample_residence_hours=("recorded_duration_min", lambda s: s.sum() / 60),
        )
        .reset_index()
    )
    wip = sheets["C1 WIP theo công đoạn"].iloc[:, :2].copy()
    wip.columns = ["stage", "population_month_end_wip_mean"]
    rework = sheets["B1 Tỷ lệ làm lại"].iloc[:, [0, 5, 6]].copy()
    rework.columns = ["stage", "population_mean_repeat_operations", "population_equivalent_r"]
    for col in rework.columns[1:]:
        rework[col] = pd.to_numeric(rework[col], errors="coerce")
    evidence = wip.merge(rework, on="stage", how="left").merge(observed, on="stage", how="left")
    evidence["wip_rank"] = evidence.population_month_end_wip_mean.rank(method="min", ascending=False)
    evidence["screening_category"] = np.select(
        [
            (evidence.wip_rank.le(5) & evidence.population_mean_repeat_operations.ge(0.5)),
            evidence.wip_rank.le(5),
        ],
        ["high_stock_and_rework", "stock_accumulation"],
        default="other_stage",
    )
    evidence["interpretation"] = (
        "Candidate for investigation; stock/rework/gaps do not establish capacity bottleneck"
    )
    csv(evidence.sort_values("wip_rank"), ctx.directory("process") / "bottleneck_evidence.csv")
    csv(
        annotated[["event_id", "source_row", "case_id", "stage", "bpmn_activity", "paint_layer"]],
        ctx.directory("process") / "event_stage_mapping.csv",
    )
    json_out(
        {
            "screening_rule": "Top five stage WIP stocks plus mean repeat operations >=0.5 flags high_stock_and_rework",
            "status": "Transparent descriptive screening, not a fitted bottleneck classifier",
            "denominators": {
                "sample": "8 purposive histories; event-level calendar measurements",
                "WIP": "C1 average month-end stock snapshots",
                "rework": "B1 repeats per completed product",
            },
            "QC_assignment": "Upstream stage inspected, following B0; no join on anonymized TRxxx/Axxx IDs",
            "remaining_unknown": ["capacity", "utilization", "arrivals", "product mix", "causal explanation"],
        },
        ctx.directory("process") / "bottleneck_contract.json",
    )


def process_analysis(ctx, events, sheets):
    out = ctx.directory("process")
    figures = ctx.directory("figures")
    bottleneck_evidence(ctx, events, sheets)
    cases = []
    for case_id, g in events.groupby("case_id", sort=False):
        control = g[g.include_control]
        first = control.drop_duplicates("activity_layer")
        elapsed = (g.end_time.max() - g.start_time.min()).total_seconds() / 60
        cases.append(
            {
                "case_id": case_id,
                "product_id": g.product_id.iloc[0],
                "events": len(g),
                "observed_start": g.start_time.min(),
                "observed_end": g.end_time.max(),
                "observed_span_days": elapsed / 1440,
                "inter_scan_gap_days": g.gap_min.sum() / 1440,
                "recorded_residence_days": g.recorded_duration_min.sum() / 1440,
                "gap_to_span_ratio": g.gap_min.sum() / elapsed,
                "first_observed_standard_min": first.standard_min.sum(min_count=1),
                "standard_to_span_proxy": first.standard_min.sum(min_count=1) / elapsed,
                "defects": g.outcome.eq("FAIL - DEFECT").sum(),
                "last_activity": g.activity_mes.iloc[-1],
                "last_outcome": g.outcome.iloc[-1],
                "completion_evidence": "stock_receipt_at_pack"
                if ((g.activity_mes.eq("Đóng gói") & g.outcome.eq("STOCK.RCV")).any())
                else "not_confirmed_by_explicit_stock_receipt",
                "negative_durations": (~g.duration_valid).sum(),
            }
        )
    cases = pd.DataFrame(cases)
    csv(cases, out / "case_metrics.csv")

    # Raw clock measurements partitioned by raw MES event (not merged timer intervals).
    task = (
        events.groupby("bpmn_activity", sort=False)
        .agg(
            events=("event_id", "size"),
            cases=("case_id", "nunique"),
            gap_hours=("gap_min", lambda s: s.sum() / 60),
            residence_hours=("recorded_duration_min", lambda s: s.sum() / 60),
            gap_median_hours=("gap_min", lambda s: s.median() / 60),
            gap_p90_hours=("gap_min", lambda s: s.quantile(0.9) / 60),
            intercompletion_hours=("intercompletion_min", lambda s: s.sum() / 60),
        )
        .reset_index()
        .sort_values("gap_hours", ascending=False)
    )
    csv(task, out / "task_timing.csv")
    sensitivity = []
    for label, subset in [
        ("all_events", events),
        ("exclude_case01", events[events.case_id.ne("CASE01")]),
        ("exclude_case07", events[events.case_id.ne("CASE07")]),
        ("exclude_both_long_cases", events[~events.case_id.isin(["CASE01", "CASE07"])]),
    ]:
        for activity, g in subset.groupby("bpmn_activity"):
            sensitivity.append(
                {
                    "subset": label,
                    "activity": activity,
                    "gap_hours": g.gap_min.sum() / 60,
                    "residence_hours": g.recorded_duration_min.sum() / 60,
                    "n_events": len(g),
                    "n_cases": g.case_id.nunique(),
                }
            )
    csv(pd.DataFrame(sensitivity), out / "timing_sensitivity.csv")

    qc = events[
        events.activity_type.eq("Kiểm tra")
        & events.outcome.isin(["PASS", "FAIL - DEFECT"])
        & events.include_control
    ].copy()
    qc["is_pass"] = qc.outcome.eq("PASS")
    qc_summary = (
        qc.groupby("bpmn_activity")
        .agg(checks=("event_id", "size"), passes=("is_pass", "sum"), sample_cases=("case_id", "nunique"))
        .reset_index()
    )
    qc_summary["observed_pass_fraction"] = qc_summary.passes / qc_summary.checks
    csv(qc_summary, out / "qc_outcomes.csv")
    first_qc = qc.drop_duplicates(["case_id", "activity_layer"])
    first_summary = (
        first_qc.groupby("bpmn_activity")
        .agg(observed_first_checks=("event_id", "size"), first_passes=("is_pass", "sum"))
        .reset_index()
    )
    first_summary["first_observed_pass_fraction"] = (
        first_summary.first_passes / first_summary.observed_first_checks
    )
    csv(first_summary, out / "first_observed_qc_outcomes.csv")
    layer_summary = (
        qc.groupby(["bpmn_activity", "paint_layer"])
        .agg(checks=("event_id", "size"), passes=("is_pass", "sum"))
        .reset_index()
    )
    layer_summary["failures"] = layer_summary.checks - layer_summary.passes
    csv(layer_summary, out / "qc_by_layer.csv")

    repeats = (
        events[events.include_control]
        .groupby(["case_id", "product_id", "bpmn_activity", "paint_layer"], dropna=False)
        .agg(observed_visits=("event_id", "size"), event_ids=("event_id", lambda s: "|".join(s)))
        .reset_index()
    )
    repeats["additional_observed_visits"] = (repeats.observed_visits - 1).clip(lower=0)
    csv(repeats, out / "repeated_visits_by_layer.csv")
    paint_visits = repeats[repeats.bpmn_activity.eq(PAINT)].copy()
    csv(paint_visits, out / "paint_repeated_visits.csv")

    defects = events[events.outcome.eq("FAIL - DEFECT")].copy()
    # Prefixes differ by MES subsystem; strip codes but retain original strings in events.csv.
    defects["defect_name"] = (
        defects.outcome_detail.astype(str).str.split("|", regex=False).str[-1].str.strip()
    )
    pareto = (
        defects.groupby("defect_name")
        .agg(count=("event_id", "size"), cases=("case_id", "nunique"))
        .reset_index()
    )
    pareto = pareto.sort_values("count", ascending=False)
    pareto["fraction"] = pareto["count"] / len(defects)
    pareto["cumulative_fraction"] = pareto.fraction.cumsum()
    csv(pareto, out / "defect_pareto.csv")
    csv(
        defects[["event_id", "source_row", "case_id", "paint_layer", "outcome_detail", "defect_name"]],
        out / "defect_evidence.csv",
    )

    timers = []
    for row in events[events.handling.eq("merged_timer")].itertuples():
        after = events[
            (events.case_id.eq(row.case_id))
            & (events.source_row.gt(row.paired_source_row))
            & events.activity_mes.str.startswith("QC7")
            & events.outcome.isin(["PASS", "FAIL - DEFECT"])
        ]
        next_qc = after.iloc[0] if len(after) else None
        timers.append(
            {
                "event_id": row.event_id,
                "case_id": row.case_id,
                "product_id": row.product_id,
                "block_source_row": row.source_row,
                "unblock_source_row": row.paired_source_row,
                "start": row.start_time,
                "end": row.end_time,
                "timer_hours": row.timer_hours,
                "under_72h": row.timer_hours < 72,
                "next_qc_event_id": next_qc.event_id if next_qc is not None else None,
                "post_unlock_gap_hours": (next_qc.start_time - row.end_time).total_seconds() / 3600
                if next_qc is not None
                else np.nan,
            }
        )
    timers = pd.DataFrame(timers)
    csv(timers, out / "timer_evidence.csv")

    control = events[events.include_control].copy()
    for col in ["event_id", "bpmn_activity", "resource"]:
        control[f"previous_{col}"] = control.groupby("case_id")[col].shift()
    pairs = control[control.previous_bpmn_activity.notna()]
    dfg = (
        pairs.groupby(["previous_bpmn_activity", "bpmn_activity"])
        .agg(frequency=("event_id", "size"), n_cases=("case_id", "nunique"))
        .reset_index()
    )
    csv(dfg, out / "dfg.csv")
    # Observed consecutive performers; not a measured organizational handover.
    handoffs = pairs[pairs.previous_resource.ne(pairs.resource)]
    social = handoffs.groupby(["previous_resource", "resource"]).size().rename("frequency").reset_index()
    csv(social, out / "performer_transitions.csv")
    csv(
        control.groupby("resource")
        .size()
        .rename("observed_events")
        .reset_index()
        .sort_values("observed_events", ascending=False),
        out / "performer_event_counts.csv",
    )

    # Use supplied population summaries as an independent evidence stream, with source sheet preserved.
    for key, name in [
        ("C1 WIP theo công đoạn", "population_wip"),
        ("B1 Tỷ lệ làm lại", "population_rework"),
        ("B3 Tỷ lệ hủy", "population_scrap"),
    ]:
        csv(sheets[key], out / f"{name}.csv")
    json_out(
        {
            "measurement": "calendar time, no working-calendar adjustment",
            "case_span_median_days": cases.observed_span_days.median(),
            "case_span_mean_days": cases.observed_span_days.mean(),
            "total_observed_case_days": cases.observed_span_days.sum(),
            "inter_scan_gap_to_span_ratio": cases.inter_scan_gap_days.sum() / cases.observed_span_days.sum(),
            "observed_defects": len(defects),
            "observed_paint_visits": int(paint_visits.observed_visits.sum()),
            "observed_paint_case_layers": len(paint_visits),
            "additional_observed_paint_visits": int(paint_visits.additional_observed_visits.sum()),
            "interpretation": [
                "Repeated visits within case/layer are rework candidates, not all proven defect repairs",
                "A next layer is planned work, never counted as same-layer rework",
                "QC pass fractions are per observed check in a biased sample",
                "Standards are supplied BOM estimates, not measured value-added time",
                "Performer transition counts do not establish staff utilization",
            ],
        },
        out / "summary.json",
    )

    plt = plot_setup()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(cases.case_id, cases.observed_span_days, color="#277da8")
    ax.set(ylabel="Ngày theo lịch", title="Khoảng thời gian quan sát của 8 case — chưa xác nhận hoàn tất")
    save_plot(fig, figures / "01_observed_case_spans")
    top = task.head(12).sort_values("gap_hours")
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.barh(top.bpmn_activity, top.gap_hours, label="Khoảng cách giữa lần quét", color="#277da8")
    ax.barh(
        top.bpmn_activity,
        top.residence_hours,
        left=top.gap_hours,
        label="Thời gian ghi nhận tại trạm",
        color="#f7a35c",
    )
    ax.set(
        xlabel="Tổng giờ của mẫu", title="Thời gian theo task — hai thành phần đều có thể chứa thời gian chờ"
    )
    ax.legend(fontsize=8)
    save_plot(fig, figures / "02_task_times")
    top = pareto.head(10)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.barh(top.defect_name.iloc[::-1], top["count"].iloc[::-1], color="#d6654b")
    ax.set(xlabel="Lần ghi nhận lỗi", title="Lỗi trong 8 case được chọn — không phải tỷ lệ lỗi toàn nhà máy")
    save_plot(fig, figures / "03_defects")
    return cases
