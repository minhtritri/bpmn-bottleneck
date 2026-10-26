"""Tests for consequential assumptions: leakage, chronology, BPMN and scenarios."""

import networkx as nx
import numpy as np
import pandas as pd

from bpmn_project.features import BASE_FEATURES, calendar_features
from bpmn_project.graph_ml import align_embedding, graphs_by_month, transition_probabilities
from bpmn_project.mining import next_observable
from bpmn_project.models import evaluate, fit_predict
from bpmn_project.simulation import repeat_workload

SETTINGS = {
    "history_months": 6,
    "min_history": 3,
    "surge_ratio": 1.5,
    "surge_min_wip": 20,
    "top_fraction": 0.2,
}


def sample_monthly():
    rows = []
    for node in ["A", "B"]:
        for i, month in enumerate(pd.period_range("2020-01", "2020-12", freq="M")):
            if str(month) == "2020-05":
                continue
            rows.append(
                {
                    "ym": str(month),
                    "node": node,
                    "activity_id": node,
                    "department": "production",
                    "wip": (i + 1) * (10 if node == "A" else 3),
                    "rework": 1,
                    "scrap": 0,
                }
            )
    return pd.DataFrame(rows)


def test_calendar_gap_is_not_previous_observation():
    panel = calendar_features(sample_monthly(), SETTINGS)
    june = panel[(panel.node == "A") & (panel.ym == "2020-06")].iloc[0]
    assert pd.isna(june.wip_lag1)
    assert june.wip_lag2 == 40
    assert june.gap_months == 2
    april = panel[(panel.node == "A") & (panel.ym == "2020-04")].iloc[0]
    assert not april.eligible  # missing May must not become a June target


def test_future_changes_cannot_change_past_features_or_graph_weights():
    original = sample_monthly()
    changed = original.copy()
    changed.loc[changed.ym >= "2020-09", "wip"] *= 1000
    a, b = calendar_features(original, SETTINGS), calendar_features(changed, SETTINGS)
    pd.testing.assert_frame_equal(a[a.ym < "2020-09"][BASE_FEATURES], b[b.ym < "2020-09"][BASE_FEATURES])
    routing = pd.DataFrame([{"src": "A", "dst": "B", "n_bom": 1, "n_mes": 900}])
    _, ga, _, _ = graphs_by_month(a, routing, {"history_months": 3})
    _, gb, _, _ = graphs_by_month(b, routing, {"history_months": 3})
    assert ga["2020-08"]["A"]["B"]["weight"] == gb["2020-08"]["A"]["B"]["weight"]


def test_targets_are_next_calendar_month_and_top_budget_exact():
    panel = calendar_features(sample_monthly(), SETTINGS)
    for month, group in panel[panel.observed_month].groupby("ym"):
        assert group.current_top20.sum() == 1
    row = panel[(panel.node == "A") & (panel.ym == "2020-07")].iloc[0]
    assert row.ym_next == "2020-08"
    assert row.wip_next == 80


def test_node2vec_return_and_outward_bias_are_real_second_order():
    graph = nx.Graph()
    graph.add_edge("previous", "current", weight=1)
    graph.add_edge("current", "outward", weight=1)
    probabilities = transition_probabilities(
        graph, "previous", "current", ["previous", "outward"], p=2, q=0.5
    )
    np.testing.assert_allclose(probabilities, [0.2, 0.8])


def test_procrustes_recovers_rotated_embedding():
    rng = np.random.default_rng(42)
    reference = rng.normal(size=(54, 16))
    rotation, _ = np.linalg.qr(rng.normal(size=(16, 16)))
    aligned, error = align_embedding(reference @ rotation, reference)
    np.testing.assert_allclose(aligned, reference, atol=1e-10)
    assert error < 1e-10


def test_structural_check_cannot_skip_required_task():
    graph = nx.DiGraph([("A", "G"), ("G", "B"), ("B", "C")])
    kinds = {"A": "task", "G": "exclusiveGateway", "B": "task", "C": "task"}
    assert next_observable(graph, "A", kinds) == {"B"}


def test_repeat_scenarios_identity_monotonicity_and_expected_mean():
    u = np.random.default_rng(42).random(200000)
    base, same = repeat_workload(1.2, 10, 0, u)
    np.testing.assert_array_equal(base, same)
    _, improved = repeat_workload(1.2, 10, 0.4, u)
    assert (improved <= base).all()
    assert abs(base.mean() - 12) < 0.15
    assert abs(improved.mean() - 7.2) < 0.15


def test_metrics_report_minority_class_counts():
    metrics = evaluate([0, 0, 1, 1], [0.1, 0.9, 0.4, 0.8])
    assert [metrics[k] for k in ["TN", "FP", "FN", "TP"]] == [1, 1, 1, 1]
    assert metrics["f1"] == 0.5


def test_train_label_cannot_cross_prediction_cutoff():
    import pytest

    frame = pd.DataFrame(
        {
            "ym": ["2020-01", "2020-02", "2020-03"],
            "ym_next": ["2020-02", "2020-04", "2020-04"],
            "target": [0, 1, 1],
            "wip": [1, 2, 3],
        }
    )
    with pytest.raises(ValueError, match="crosses"):
        fit_predict(frame, "target", frame.ym < "2020-03", frame.ym == "2020-03", ["wip"], {}, 42)
