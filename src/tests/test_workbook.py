"""Integration invariants on the real supplied workbook; no expected ML score hardcoded."""

import pandas as pd
import pytest

from bpmn_project.common import ROOT, make_context, sha256
from bpmn_project.data import prepare
from bpmn_project.features import build_features
from bpmn_project.simulation import replay_gap_reduction


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    if not (ROOT.parent / "CongTyX_Event log.xlsx").exists():
        pytest.skip("Supplied workbook is not present")
    ctx = make_context(output=tmp_path_factory.mktemp("workbook_run"))
    before = sha256(ctx.workbook)
    events, sheets, _nodes, _edges = prepare(ctx)
    assert sha256(ctx.workbook) == before
    return ctx, events, sheets


def test_withdrawn_scrap_and_timer_pairing_follow_business_rules(prepared):
    _, events, _ = prepared
    pair = events[events.outcome.isin(["FAIL - SCRAP", "FAIL - RECOVER"])]
    assert len(pair) == 2
    assert not pair.include_control.any()
    assert pair.handling.eq("withdrawn_scrap_status").all()
    timers = events[events.handling.eq("merged_timer")]
    assert len(timers) == 2
    assert timers.timer_hours.between(70, 72).all()
    for row in timers.itertuples():
        mate = events[events.source_row.eq(row.paired_source_row)].iloc[0]
        assert row.case_id == mate.case_id
        assert row.station_id == mate.station_id
        assert row.end_time == mate.source_end_time
        assert not mate.include_control
    assert events.loc[events.handling.eq("timer_end_merged"), "occurrence"].isna().all()


def test_clock_errors_are_preserved_not_repaired(prepared):
    _, events, _ = prepared
    errors = events[events.raw_duration_min.lt(0)]
    assert len(errors) == 2
    assert errors.recorded_duration_min.isna().all()
    assert errors.source_end_time.lt(errors.source_start_time).all()
    assert errors.include_control.all()  # timing errors do not erase genuine control observations


def test_identity_replay_preserves_observed_case_span(prepared):
    _, events, _ = prepared
    replay = replay_gap_reduction(events, 0)
    pd.testing.assert_series_equal(
        replay.baseline_observed_span_hours, replay.scenario_span_hours, check_names=False
    )
    reduced = replay_gap_reduction(events, 0.4, checklist_min=2)
    assert reduced.scenario_span_hours.gt(0).all()


def test_real_monthly_dataset_has_disjoint_cutoffs_and_no_future_features(prepared):
    ctx, _, sheets = prepared
    panel, dataset = build_features(ctx, sheets)
    train = dataset[dataset.split.eq("train")]
    test = dataset[dataset.split.eq("test")]
    assert train.ym.max() < test.ym.min()
    assert train.ym_next.max() <= test.ym.min()
    assert set(test.ym_next) == set(pd.period_range("2020-08", "2021-04", freq="M").astype(str))
    assert not dataset.duplicated(["ym", "node"]).any()
    assert len(test) == 54 * 9
    assert panel.loc[panel.ym.eq("2019-08"), "wip"].isna().all()
    assert panel.loc[panel.ym.eq("2020-02"), "wip"].isna().all()
