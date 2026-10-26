"""Conditional intervention scenarios; never claim measured factory improvement.

Three separate estimands: observed-span gap replay, per-operation repeat workload,
and QC7 timer/dispatch replay. They are intentionally not summed into a factory CT.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from .analysis import PAINT, SAND
from .common import csv, json_out, plot_setup, save_plot


def replay_gap_reduction(events, reduction, checklist_min=0):
    if not 0 <= reduction <= 1 or checklist_min < 0:
        raise ValueError("Invalid scenario intervention")
    rows = []
    for case, g in events.groupby("case_id", sort=False):
        span = (g.end_time.max() - g.start_time.min()).total_seconds() / 60
        eligible_gap = g.loc[g.bpmn_activity.eq(SAND), "gap_min"].sum()
        paint_visits = g.bpmn_activity.eq(PAINT).sum()
        overhead = checklist_min * paint_visits
        saving = reduction * eligible_gap - overhead
        rows.append(
            {
                "case_id": case,
                "baseline_observed_span_hours": span / 60,
                "eligible_inter_scan_gap_hours": eligible_gap / 60,
                "assumed_gap_reduction": reduction,
                "checklist_overhead_hours": overhead / 60,
                "conditional_saving_hours": saving / 60,
                "scenario_span_hours": (span - saving) / 60,
                "interpretation": "Replay assumes targeted gaps compress on a sequential serial timeline; capacity not modeled",
            }
        )
    return pd.DataFrame(rows)


def repeat_workload(mean_repeats, duration_min, reduction, uniforms):
    """Common random numbers couple geometric repeat scenarios monotonically.

    For geometric failures N, E[N]=R and r=R/(1+R). This is an equivalent
    distribution assumption, not evidence that actual retries are independent.
    """
    if mean_repeats < 0 or duration_min < 0 or not 0 <= reduction <= 1:
        raise ValueError("Invalid repeat scenario")

    def count(r_mean):
        if r_mean == 0:
            return np.zeros_like(uniforms)
        r = r_mean / (1 + r_mean)
        return np.floor(np.log1p(-uniforms) / np.log(r))

    base = count(mean_repeats) * duration_min
    changed = count(mean_repeats * (1 - reduction)) * duration_min
    return base, changed


def focused_bpmn(path, to_be=False):
    """A scoped non-executable projection, separate from the supplied full model."""
    ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
    ET.register_namespace("bpmn", ns)
    root = ET.Element(
        f"{{{ns}}}definitions",
        {"id": "Definitions_PaintScenario", "targetNamespace": "https://example.org/congtyx/scenarios"},
    )
    proc = ET.SubElement(
        root, f"{{{ns}}}process", {"id": "Paint_ToBe" if to_be else "Paint_AsIs", "isExecutable": "false"}
    )
    doc = ET.SubElement(proc, f"{{{ns}}}documentation")
    doc.text = (
        "Scoped conceptual projection of sanding/painting per layer. Masking and factory-level routing omitted. "
        "Outcome/layer guards require business data; no simulated capacity claim. "
        "To-Be adds a 2-minute assumed checklist; its efficacy is a sensitivity parameter."
    )
    elements = [
        ("start", "startEvent", "Đầu vào công đoạn"),
        ("sand", "task", SAND),
        ("sand_qc", "task", "QC3 / QC4 – Kiểm tra chà nhám"),
        ("sand_decision", "exclusiveGateway", "Kết quả chà nhám?"),
        ("prep", "task", "Chuẩn bị bề mặt"),
        ("paint", "task", PAINT),
        ("qc6", "task", "QC6 – Kiểm tra sau sơn từng lớp"),
        ("decision", "exclusiveGateway", "Kết quả QC6?"),
        ("layer", "exclusiveGateway", "Còn lớp sơn?"),
        ("end", "endEvent", "Hoàn tất các lớp"),
        ("scrap", "endEvent", "Hủy"),
    ]
    if to_be:
        elements.append(("checklist", "task", "Kiểm tra điều kiện sơn trước khi sơn"))
    for node, kind, label in elements:
        task = ET.SubElement(proc, f"{{{ns}}}{kind}", {"id": node, "name": label})
        if to_be and node == "sand":
            ET.SubElement(
                task, f"{{{ns}}}documentation"
            ).text = "Điều phối ưu tiên/WIP limit là chính sách giả định bên ngoài luồng; chưa có số liệu công suất để hiệu chỉnh."
    flows = [
        ("start", "sand", ""),
        ("sand", "sand_qc", ""),
        ("sand_qc", "sand_decision", ""),
        ("sand_decision", "sand", "Sửa được"),
        ("sand_decision", "prep", "Đạt"),
        ("sand_decision", "scrap", "Hủy"),
        ("paint", "qc6", ""),
        ("qc6", "decision", ""),
        ("decision", "sand", "Không đạt, sửa được"),
        ("decision", "scrap", "Hủy"),
        ("decision", "layer", "Đạt"),
        ("layer", "sand", "Còn lớp: công việc theo tuyến, không phải rework"),
        ("layer", "end", "Đủ lớp"),
    ]
    flows += [("prep", "checklist", ""), ("checklist", "paint", "")] if to_be else [("prep", "paint", "")]
    for i, (source, target, label) in enumerate(flows):
        ET.SubElement(
            proc,
            f"{{{ns}}}sequenceFlow",
            {"id": f"flow_{i}", "sourceRef": source, "targetRef": target, "name": label},
        )
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def simulate(ctx, events, sheets):
    out = ctx.directory("scenarios")
    settings = ctx.config["simulation"]
    replay_rows = []
    for reduction in settings["queue_reductions"]:
        # Include intervention cost, and also a no-checklist gap-only scenario to isolate effects.
        for overhead in [0.0, 2.0]:
            result = replay_gap_reduction(events, reduction, overhead)
            result["checklist_minutes_per_observed_paint"] = overhead
            replay_rows.append(result)
    replay = pd.concat(replay_rows, ignore_index=True)
    csv(replay, out / "gap_replay_by_case.csv")
    aggregate = (
        replay.groupby(["assumed_gap_reduction", "checklist_minutes_per_observed_paint"])
        .agg(
            mean_baseline_hours=("baseline_observed_span_hours", "mean"),
            mean_scenario_hours=("scenario_span_hours", "mean"),
            mean_saving_hours=("conditional_saving_hours", "mean"),
            median_saving_hours=("conditional_saving_hours", "median"),
        )
        .reset_index()
    )
    csv(aggregate, out / "gap_replay_summary.csv")

    # Population R applies to repeat operations per completed product, not per planned layer.
    pop = sheets["B1 Tỷ lệ làm lại"]
    rows = []
    rng = np.random.default_rng(ctx.config["experiment"]["seed"])
    uniforms = rng.random((settings["replications"], 100))
    for stage, activity in [("Chà nhám", SAND), ("Sơn", PAINT)]:
        R = float(pop.loc[pop.iloc[:, 0].eq(stage)].iloc[0, 5])
        standards = events.loc[events.bpmn_activity.eq(activity), "standard_min"].dropna()
        duration = float(standards.median())
        for reduction in settings["rework_reductions"]:
            base, changed = repeat_workload(R, duration, reduction, uniforms)
            base, changed = base.sum(axis=1), changed.sum(axis=1)
            savings = base - changed
            rows.append(
                {
                    "stage": stage,
                    "products_per_replication": 100,
                    "population_mean_repeats_per_completed_product": R,
                    "equivalent_r": R / (1 + R),
                    "standard_minutes_per_repeat_proxy": duration,
                    "assumed_relative_reduction_in_mean_repeats": reduction,
                    "baseline_repeat_workload_mean_minutes": base.mean(),
                    "scenario_repeat_workload_mean_minutes": changed.mean(),
                    "saving_mean_minutes": savings.mean(),
                    "saving_p025_minutes": np.quantile(savings, 0.025),
                    "saving_p975_minutes": np.quantile(savings, 0.975),
                    "analytic_expected_saving_minutes": 100 * R * duration * reduction,
                    "interpretation": "Repeat-operation standard workload only; excludes planned layers, queue, scrap and full process CT",
                }
            )
    workload = pd.DataFrame(rows)
    csv(workload, out / "repeat_workload_sensitivity.csv")
    # QC7: keep required timer, compare unlock-to-QC delay; do not remove required stability time.
    timer_file = ctx.directory("process") / "timer_evidence.csv"
    timers = pd.read_csv(timer_file)
    if len(timers):
        timers["baseline_block_to_qc_hours"] = timers.timer_hours + timers.post_unlock_gap_hours
        timers["scenario_timer_hours"] = np.maximum(timers.timer_hours, settings["timer_hours"])
        timers["scenario_dispatch_hours"] = timers.post_unlock_gap_hours.clip(
            lower=0, upper=settings["qc_dispatch_delay_hours"]
        )
        timers["scenario_block_to_qc_hours"] = timers.scenario_timer_hours + timers.scenario_dispatch_hours
        timers["conditional_saving_hours"] = (
            timers.baseline_block_to_qc_hours - timers.scenario_block_to_qc_hours
        )
    csv(timers, out / "qc7_timer_dispatch_replay.csv")
    focused_bpmn(out / "painting_as_is_projection.bpmn")
    focused_bpmn(out / "painting_to_be_projection.bpmn", to_be=True)
    json_out(
        {
            "scope": "Three separate scenario estimands; no combined factory-wide benefit is asserted",
            "gap_replay": "Assumed percentage compression of positive inter-scan gaps entering sanding; same observed case timelines",
            "checklist_cost": "0 or 2 assumed minutes per observed painting event; efficacy not estimated from observational logs",
            "repeat_workload": "B1 mean repeated operations per completed product, geometric-equivalent repeats, median supplied BOM standard per operation",
            "planned_layers": "Excluded from repeated workload; not mistaken for defects",
            "randomness": "Common random uniforms pair As-Is/To-Be; quantiles are simulation variation, not causal confidence intervals",
            "timer": "At least 72 hours plus an assumed dispatch delay capped at 2h; capacity to meet this is unverified",
            "scrap": "B3 proportions use total factory input denominator; not used as conditional branch probabilities",
            "WIP": "C1 is month-end stock. Little-law times are not recalibrated as per-visit queue times",
            "ToBe_models": "Focused conceptual projections, not replacements for full supplied BPMN; no BPMNDI layout",
            "actions": [
                {
                    "issue": "Repeated sanding/painting late layers",
                    "owner": "Production + QC",
                    "change": "Pre-paint checklist and defect-cause review",
                    "parameter": "relative mean-repeat reduction",
                    "guardrail": "Retain mandatory QC; record defect and layer",
                },
                {
                    "issue": "Long inter-scan gaps into sanding",
                    "owner": "Production planning",
                    "change": "Trial dispatch priority / WIP policy",
                    "parameter": "gap compression fraction",
                    "guardrail": "No claim of feasible WIP limit without arrivals/capacity data",
                },
                {
                    "issue": "QC7 timer and post-unlock delay",
                    "owner": "MES + QC",
                    "change": "Enforce 72h and schedule QC after release",
                    "parameter": "dispatch delay cap",
                    "guardrail": "Never shorten required stabilization",
                },
            ],
        },
        out / "scenario_contract.json",
    )
    plt = plot_setup()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for overhead, group in aggregate.groupby("checklist_minutes_per_observed_paint"):
        axes[0].plot(
            group.assumed_gap_reduction * 100,
            group.mean_saving_hours,
            marker="o",
            label=f"Checklist {overhead:g} phút/lượt sơn",
        )
    axes[0].axhline(0, color="gray", linewidth=0.7)
    axes[0].set(
        xlabel="Giả định giảm khoảng cách vào chà nhám (%)",
        ylabel="Giờ tiết kiệm TB/case",
        title="Replay trên mẫu — không mô phỏng năng lực",
    )
    axes[0].legend(fontsize=8)
    for stage, group in workload.groupby("stage"):
        axes[1].plot(
            group.assumed_relative_reduction_in_mean_repeats * 100,
            group.analytic_expected_saving_minutes / 60,
            marker="o",
            label=stage,
        )
    axes[1].set(
        xlabel="Giả định giảm số lượt làm lại TB (%)",
        ylabel="Giờ định mức tiết kiệm/100 SP",
        title="Khối lượng làm lại — không phải Cycle Time",
    )
    axes[1].legend()
    save_plot(fig, ctx.directory("figures") / "07_scenario_sensitivity")
    return aggregate
