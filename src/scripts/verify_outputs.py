"""Independently recompute output metrics and saved-model predictions after a full run."""

import joblib
import numpy as np
import pandas as pd

from bpmn_project.common import ROOT, csv, json_out, sha256
from bpmn_project.models import evaluate


def main():
    import json

    out = ROOT / "outputs"
    status = json.loads((out / "metadata/run_all.json").read_text())
    assert status["status"] == "success" and not status["quick"]
    manifest = json.loads((out / "metadata/manifest.json").read_text())
    for source in manifest["sources"]:
        assert sha256(ROOT.parent / source["path"]) == source["sha256"], source["path"]
    for source in manifest["project_files"]:
        assert sha256(ROOT / source["path"]) == source["sha256"], source["path"]
    predictions = pd.read_csv(out / "forecast/test_predictions.csv")
    metrics = pd.read_csv(out / "forecast/metrics_by_seed.csv")
    assert predictions.probability.between(0, 1).all()
    assert not predictions.duplicated(["target", "model", "seed", "ym", "node"]).any()
    for row in metrics.itertuples():
        group = predictions[
            (predictions.target == row.target)
            & (predictions.model == row.model)
            & (predictions.seed == row.seed)
        ]
        recalculated = evaluate(
            group.actual,
            group.probability,
            manifest["configuration"]["experiment"]["classification_threshold"],
        )
        for key, value in recalculated.items():
            assert np.isclose(getattr(row, key), value, atol=1e-8, equal_nan=True), (row.model, key)
    dataset = pd.read_csv(out / "forecast/model_dataset.csv")
    seed = manifest["configuration"]["experiment"]["seed"]
    graph = pd.read_csv(out / f"forecast/node_embeddings_seed_{seed}.csv")
    graph = graph.merge(pd.read_csv(out / "forecast/graph_metrics.csv"), on=["ym", "node"])
    frame = dataset.merge(graph, on=["ym", "node"], validate="one_to_one")
    holdout = frame[frame.split.eq("test")].copy()
    model_count = 0
    for path in sorted((out / "models").glob("*.joblib")):
        bundle = joblib.load(path)
        target, name = path.stem.split("__")
        model = bundle["pipeline"]
        positive = list(model.named_steps["model"].classes_).index(1)
        actual = model.predict_proba(holdout)[:, positive]
        expected = predictions[
            (predictions.target == target) & (predictions.model == name) & (predictions.seed == seed)
        ]
        compared = (
            holdout[["ym", "node"]]
            .assign(recomputed=actual)
            .merge(expected[["ym", "node", "probability"]], on=["ym", "node"], validate="one_to_one")
        )
        np.testing.assert_allclose(compared.recomputed, compared.probability, atol=1e-8, rtol=1e-8)
        model_count += 1
    replay = pd.read_csv(out / "scenarios/gap_replay_by_case.csv")
    identity = replay[replay.assumed_gap_reduction.eq(0) & replay.checklist_minutes_per_observed_paint.eq(0)]
    np.testing.assert_allclose(identity.baseline_observed_span_hours, identity.scenario_span_hours)
    assert replay.scenario_span_hours.gt(0).all()
    repeats = pd.read_csv(out / "scenarios/repeat_workload_sensitivity.csv")
    for row in repeats.itertuples():
        r_mean = row.population_mean_repeats_per_completed_product
        scale = row.standard_minutes_per_repeat_proxy
        n = manifest["configuration"]["simulation"]["replications"]
        standard_error = scale * np.sqrt(100 * r_mean * (1 + r_mean) / n)
        expected = 100 * r_mean * scale
        assert abs(row.baseline_repeat_workload_mean_minutes - expected) < 5 * standard_error
    result = {
        "status": "passed",
        "input_and_code_hashes": "unchanged since final full run",
        "metric_groups_recomputed": len(metrics),
        "saved_models_reproduced": model_count,
        "prediction_rows_checked": len(predictions),
        "scenario_checks": "identity, positive spans, Monte Carlo mean within 5 standard errors",
    }
    json_out(result, out / "metadata/verification.json")
    # Refresh inventory after notebook execution and verification, excluding its own hash.
    inventory = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "artifact_inventory.csv":
            item = {
                "artifact": str(path.relative_to(out)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            if path.suffix == ".csv":
                data = pd.read_csv(path)
                item.update(rows=len(data), columns=len(data.columns))
            inventory.append(item)
    csv(pd.DataFrame(inventory), out / "metadata/artifact_inventory.csv")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
