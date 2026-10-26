"""Read the immutable workbook; derive event semantics independently of A6 formula caches."""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from collections import Counter

import numpy as np
import pandas as pd

from .common import csv, json_out, manifest

NS = {"b": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
RAW_NAMES = dict(
    zip(
        [
            "Case ID",
            "Mã SP",
            "Cấp",
            "Công đoạn",
            "Mã trạm",
            "Activity",
            "Start Timestamp",
            "Complete Timestamp",
            "Resource",
            "Kết quả",
            "Kết quả chi tiết",
            "Thời gian thực tế (phút)",
            "Định mức (phút)",
            "Chênh lệch so định mức (phút)",
            "Thực tế / Định mức (lần)",
            "Thời gian chờ trước công đoạn (phút)",
            "Thời gian từ lần quét trước (phút)",
            "Mã công đoạn BOM",
            "Ghi chú định mức",
        ],
        [
            "case_id",
            "product_id",
            "product_level",
            "department",
            "station_id",
            "activity_mes",
            "start_time",
            "end_time",
            "resource",
            "outcome",
            "outcome_detail",
            "cached_duration_min",
            "standard_min",
            "cached_delta_min",
            "cached_ratio",
            "cached_gap_min",
            "cached_intercompletion_min",
            "bom_operation_id",
            "standard_note",
        ],
    )
)


def load_workbook(ctx):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.read_excel(ctx.workbook, sheet_name=None, engine="openpyxl")


def parse_bpmn(path):
    root = ET.parse(path).getroot()
    nodes, edges = [], []
    for proc in root.findall("b:process", NS):
        for el in proc:
            kind = el.tag.split("}")[-1]
            if kind == "sequenceFlow":
                edges.append(
                    {
                        "process_id": proc.get("id"),
                        "source": el.get("sourceRef"),
                        "target": el.get("targetRef"),
                        "condition": el.get("name", ""),
                    }
                )
            elif kind.endswith(("Event", "Gateway")) or kind in {"task", "callActivity"}:
                nodes.append(
                    {
                        "process_id": proc.get("id"),
                        "node_id": el.get("id"),
                        "label": el.get("name", ""),
                        "kind": kind,
                        "called_element": el.get("calledElement", ""),
                    }
                )
    return pd.DataFrame(nodes), pd.DataFrame(edges)


def normalize_events(raw, mapping, nodes):
    """Keep source order. Never repair clocks, infer readiness, or remove real defects.

    BLOCK/UNBLOCK pairs become timer events only at QC7 and only within the same
    case/station. SCRAP immediately followed by same-station RECOVER is withdrawn.
    Unknown tasks remain visible as log-only activities.
    """
    events = raw.rename(columns=RAW_NAMES).copy()
    events.insert(0, "source_row", np.arange(2, len(events) + 2))
    events.insert(0, "event_id", events.source_row.map(lambda r: f"MES-{r:05d}"))
    for col in ["start_time", "end_time"]:
        events[col] = pd.to_datetime(events[col], errors="coerce")
        events[f"source_{col}"] = events[col].copy()
    lookup = mapping.set_index("Activity (MES)")
    for target, source in [
        ("bpmn_activity", "Task BPMN"),
        ("paint_layer", "Lớp sơn"),
        ("bpmn_figure", "Hình BPMN"),
        ("activity_type", "Loại hoạt động"),
    ]:
        events[target] = events.activity_mes.map(lookup[source])
    events["paint_layer"] = pd.to_numeric(events.paint_layer, errors="coerce")
    events["raw_duration_min"] = (events.end_time - events.start_time).dt.total_seconds() / 60
    events["duration_valid"] = events.raw_duration_min.ge(0) & events.raw_duration_min.notna()
    events["recorded_duration_min"] = events.raw_duration_min.where(events.duration_valid)
    previous_end = events.groupby("case_id", sort=False).end_time.shift()
    events["previous_event_id"] = events.groupby("case_id", sort=False).event_id.shift()
    events["raw_gap_min"] = (events.start_time - previous_end).dt.total_seconds() / 60
    events["gap_min"] = events.raw_gap_min.where(events.raw_gap_min.ge(0))
    events["intercompletion_min"] = ((events.end_time - previous_end).dt.total_seconds() / 60).where(
        lambda s: s.ge(0)
    )
    events["include_control"] = True
    events["handling"] = "keep"
    events["paired_source_row"] = pd.Series(pd.NA, index=events.index, dtype="Int64")
    for _, group in events.groupby("case_id", sort=False):
        indices = group.index.tolist()
        pending = {}
        for pos, i in enumerate(indices):
            row = events.loc[i]
            if row.outcome == "FAIL - BLOCK":
                if str(row.activity_mes).startswith("QC7"):
                    pending[row.station_id] = i
                    events.loc[i, ["include_control", "handling"]] = [False, "unpaired_timer_start"]
                else:
                    events.loc[i, ["include_control", "handling"]] = [False, "system_status"]
            elif row.outcome == "FAIL - UNBLOCK":
                if row.station_id in pending:
                    j = pending.pop(row.station_id)
                    events.loc[j, ["bpmn_activity", "end_time", "include_control", "handling"]] = [
                        "Chờ ổn định 72 giờ",
                        row.end_time,
                        True,
                        "merged_timer",
                    ]
                    events.loc[j, "paired_source_row"] = row.source_row
                    events.loc[i, "paired_source_row"] = events.loc[j, "source_row"]
                    events.loc[i, ["include_control", "handling"]] = [False, "timer_end_merged"]
                else:
                    events.loc[i, ["include_control", "handling"]] = [False, "system_status"]
            elif row.outcome == "FAIL - SCRAP" and pos + 1 < len(indices):
                j = indices[pos + 1]
                if (
                    events.loc[j, "outcome"] == "FAIL - RECOVER"
                    and events.loc[j, "station_id"] == row.station_id
                ):
                    events.loc[[i, j], "include_control"] = False
                    events.loc[[i, j], "handling"] = "withdrawn_scrap_status"
            if row.activity_type == "Vận chuyển":
                events.loc[i, ["include_control", "handling"]] = [False, "transport_timing_only"]
            if str(row.activity_mes).startswith("Che chắn bề mặt"):
                prev = events.loc[indices[pos - 1]] if pos else None
                after_paint = prev is not None and str(prev.activity_mes).startswith(
                    ("Sơn thủ công", "Sơn bằng robot")
                )
                events.loc[i, "bpmn_activity"] = "Che chắn sau sơn" if after_paint else "Che chắn trước sơn"
                if prev is not None:
                    events.loc[i, "paint_layer"] = prev.paint_layer
    timer = events.handling.eq("merged_timer")
    events["timer_hours"] = np.nan
    events.loc[timer, "timer_hours"] = (
        events.loc[timer, "end_time"] - events.loc[timer, "start_time"]
    ).dt.total_seconds() / 3600
    # Raw durations/gaps remain unmodified: merged timers are a separate analytical view.
    unknown = events.bpmn_activity.isna() | events.bpmn_activity.eq("(Chưa có trong BPMN)")
    events.loc[unknown, "bpmn_activity"] = "LOG_ONLY: " + events.loc[unknown, "activity_mes"]
    label_nodes = nodes.groupby("label").node_id.agg(lambda x: "|".join(sorted(x)))
    events["bpmn_node_candidates"] = events.bpmn_activity.map(label_nodes).fillna("")
    events["mapping_status"] = np.where(events.bpmn_node_candidates.eq(""), "unmapped", "mapped")
    events["activity_layer"] = events.bpmn_activity + events.paint_layer.map(
        lambda n: f" — lớp {int(n)}" if pd.notna(n) else ""
    )
    events["occurrence"] = pd.Series(pd.NA, index=events.index, dtype="Int64")
    included = events[events.include_control]
    events.loc[included.index, "occurrence"] = (
        included.groupby(["case_id", "activity_layer"], sort=False).cumcount() + 1
    )
    return events


def prepare(ctx, sheets=None):
    sheets = sheets or load_workbook(ctx)
    out = ctx.directory("data")
    nodes, edges = parse_bpmn(ctx.data_dir / "BPMN" / "Tong the BPMN.bpmn")
    mapping = sheets["A5 Ánh xạ BPMN"].iloc[3:65].copy()
    mapping.columns = sheets["A5 Ánh xạ BPMN"].iloc[2].tolist()
    # pandas header consumed workbook row 1; row 4 contains the actual mapping header.
    events = normalize_events(sheets["A1 Event log MES"], mapping, nodes)
    csv(events, out / "events.csv")
    csv(nodes, out / "bpmn_nodes.csv")
    csv(edges, out / "bpmn_edges.csv")
    csv(mapping, out / "activity_mapping.csv")
    for key, name in [
        ("D1 Danh mục trạm", "stations"),
        ("D2 Cạnh đồ thị", "routing_edges"),
        ("D3 Trọng số cạnh theo tháng", "supplied_edge_weights"),
        ("D4 Dữ liệu trạm-tháng", "supplied_monthly"),
        ("D5 Nhãn ùn tháng sau", "supplied_labels"),
        ("E1 So sánh mô hình", "supplied_model_results"),
        ("B1 Tỷ lệ làm lại", "population_rework"),
        ("B3 Tỷ lệ hủy", "population_scrap"),
        ("C1 WIP theo công đoạn", "population_wip"),
    ]:
        csv(sheets[key], out / f"{name}.csv")
    json_out(manifest(ctx), ctx.directory("metadata") / "manifest.json")
    audit(ctx, events, sheets, nodes, edges)
    return events, sheets, nodes, edges


def audit(ctx, events, sheets, nodes, edges):
    out = ctx.directory("audit")
    issues = []

    def add(code, severity, row=None, detail=""):
        issues.append(
            {
                "code": code,
                "severity": severity,
                "event_id": row.event_id if row is not None else "",
                "case_id": row.case_id if row is not None else "",
                "source_row": row.source_row if row is not None else None,
                "detail": detail,
            }
        )

    checks = [
        ((events.raw_duration_min < 0), "NEGATIVE_DURATION", "error"),
        ((events.raw_gap_min < 0), "NEGATIVE_SOURCE_ORDER_GAP", "warning"),
        ((events.raw_duration_min > 7 * 24 * 60), "RESIDENCE_OVER_SEVEN_DAYS", "warning"),
        (events.mapping_status.eq("unmapped") & events.include_control, "UNMAPPED_TASK", "warning"),
        (events.standard_min.isna(), "MISSING_STANDARD", "warning"),
        (events.handling.eq("unpaired_timer_start"), "UNPAIRED_TIMER_START", "warning"),
        (events.timer_hours.lt(72), "TIMER_UNDER_72H", "warning"),
    ]
    for mask, code, severity in checks:
        for row in events[mask].itertuples():
            add(code, severity, row, "Retained with flag; no automatic clock correction or deletion")
    for col in ["case_id", "activity_mes", "start_time", "end_time"]:
        for row in events[events[col].isna()].itertuples():
            add("MISSING_REQUIRED_FIELD", "error", row, col)
    if nodes.node_id.duplicated().any():
        raise ValueError("Duplicate BPMN node IDs")
    if not set(edges.source).union(edges.target).issubset(set(nodes.node_id)):
        raise ValueError("BPMN flow references missing node")
    add(
        "PARTIAL_PURPOSIVE_TRACES",
        "limitation",
        detail="8 histories selected for high rework; no population prevalence inference",
    )
    add("NO_READY_TIME", "limitation", detail="Inter-scan gaps are proxies, not measured resource queue time")
    add(
        "MONTHLY_LINEAGE_INCOMPLETE",
        "limitation",
        detail="D/E values supplied; upstream raw reports and code absent",
    )
    add(
        "ROUTING_SNAPSHOT_UNDATED",
        "limitation",
        detail="BOM topology treated as available ex ante; chronology unverified",
    )
    add(
        "NO_CAPACITY_CALENDAR",
        "limitation",
        detail="Cannot identify capacity bottleneck or calibrate resource simulation",
    )
    cached = sheets["A6 Log theo BPMN"]
    discrepancy = pd.DataFrame(
        {
            "event_id": events.event_id,
            "source_row": events.source_row,
            "code_include": events.include_control,
            "excel_include": cached["Đưa vào tuân thủ"].eq("Có"),
            "code_activity": events.bpmn_activity,
            "excel_activity": cached["Task BPMN"],
        }
    )
    csv(
        discrepancy[discrepancy.code_include.ne(discrepancy.excel_include)],
        out / "excel_control_differences.csv",
    )
    csv(pd.DataFrame(issues), out / "issues.csv")
    json_out(
        {
            "events": len(events),
            "cases": events.case_id.nunique(),
            "products": events.product_id.nunique(),
            "mes_activities": events.activity_mes.nunique(),
            "stations": events.station_id.nunique(),
            "control_events": int(events.include_control.sum()),
            "issues": dict(Counter(i["code"] for i in issues)),
            "timestamp_policy": "naive source clock, calendar hours; dates shifted by data owner; no timezone invented",
            "lineage": {
                "A1": "supplied company MES history",
                "A5": "supplied AI-assisted mapping",
                "D1_D2_D4": "supplied derived snapshot, not independently regenerated from MES",
                "A6_A11_E1_E4": "comparison only; not an input to training or scenario outcomes",
            },
        },
        out / "summary.json",
    )
