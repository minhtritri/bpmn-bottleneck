"""Chronological evaluation: simple rules, tabular RF and graph ablations."""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .common import csv, json_out, plot_setup, save_plot
from .features import BASE_FEATURES
from .graph_ml import GRAPH_FEATURES

TARGETS = ["y_top20_next", "y_surge_next"]


def evaluate(y, probabilities, threshold=0.5):
    y, probabilities = np.asarray(y, dtype=int), np.asarray(probabilities)
    pred = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    two = len(np.unique(y)) == 2
    return {
        "n": len(y),
        "positives": int(y.sum()),
        "positive_fraction": float(y.mean()),
        "precision": precision_score(y, pred, zero_division=0),
        "recall": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
        "balanced_accuracy": balanced_accuracy_score(y, pred),
        "roc_auc": roc_auc_score(y, probabilities) if two else np.nan,
        "average_precision": average_precision_score(y, probabilities) if two else np.nan,
        "TN": int(tn),
        "FP": int(fp),
        "FN": int(fn),
        "TP": int(tp),
    }


def month_bootstrap(predictions, seed=42, replications=2000):
    """Resample whole test months, retaining all stations within each sampled month."""
    monthly = []
    for _, group in predictions.groupby("ym"):
        tn, fp, fn, tp = confusion_matrix(group.actual, group.predicted, labels=[0, 1]).ravel()
        monthly.append([tn, fp, fn, tp])
    values = np.asarray(monthly)
    rng = np.random.default_rng(seed)
    sample = values[rng.integers(0, len(values), size=(replications, len(values)))].sum(axis=1)
    tn, fp, fn, tp = sample.T
    f1 = np.divide(2 * tp, 2 * tp + fp + fn, out=np.zeros(replications), where=(2 * tp + fp + fn) > 0)
    return {
        "f1_month_bootstrap_low": np.quantile(f1, 0.025),
        "f1_month_bootstrap_high": np.quantile(f1, 0.975),
        "test_months": len(values),
    }


def rf_pipeline(features, settings, seed, station_only=False):
    transformers = []
    if features:
        transformers.append(
            (
                "numeric",
                SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                features,
            )
        )
    if station_only:
        transformers.append(
            ("station", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["node"])
        )
    processor = ColumnTransformer(transformers, remainder="drop", verbose_feature_names_out=False)
    return Pipeline(
        [
            ("features", processor),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=settings["trees"],
                    max_depth=settings["max_depth"],
                    class_weight="balanced",
                    random_state=seed,
                    n_jobs=1,
                ),
            ),
        ]
    )


def fit_predict(frame, target, train_mask, test_mask, features, settings, seed, station_only=False):
    if frame.loc[train_mask, target].nunique() < 2:
        raise ValueError(f"Training target {target} has fewer than two classes")
    # Labels from the train horizon must be observable at the first prediction cutoff.
    if frame.loc[train_mask, "ym_next"].max() > frame.loc[test_mask, "ym"].min():
        raise ValueError("Training label crosses evaluation cutoff")
    model = rf_pipeline(features, settings, seed, station_only)
    model.fit(frame.loc[train_mask], frame.loc[train_mask, target])
    positive = list(model.named_steps["model"].classes_).index(1)
    probabilities = model.predict_proba(frame.loc[test_mask])[:, positive]
    return model, probabilities


def forecast(ctx, dataset, graph_seeds):
    out = ctx.directory("forecast")
    model_dir = ctx.directory("models")
    settings = ctx.config["experiment"]
    seeds = settings["seeds"]
    n2v = [f"n2v_{i}" for i in range(ctx.config["embedding"]["dimensions"])]
    variants = {
        "RF_station_only": ([], True),
        "RF_WIP": (BASE_FEATURES, False),
        "RF_WIP_graph": (BASE_FEATURES + GRAPH_FEATURES, False),
        "RF_WIP_n2v": (BASE_FEATURES + n2v, False),
        "RF_WIP_graph_n2v": (BASE_FEATURES + GRAPH_FEATURES + n2v, False),
        "RF_n2v_only": (n2v, False),
    }
    metrics, predictions, importance, validation = [], [], [], []
    for target in TARGETS:
        train, test = dataset.split.eq("train"), dataset.split.eq("test")
        observed = dataset.loc[test]
        for name, score in [
            ("majority_train", np.full(test.sum(), float(dataset.loc[train, target].mean() >= 0.5))),
            (
                "persistence",
                observed.current_top20.to_numpy()
                if target == "y_top20_next"
                else observed.persistence_surge.to_numpy(),
            ),
        ]:
            metrics.append(
                {
                    "target": target,
                    "model": name,
                    "seed": -1,
                    **evaluate(observed[target], score, settings["classification_threshold"]),
                }
            )
            predictions.extend(prediction_records(observed, target, name, -1, score, settings))
        for seed in seeds:
            frame = dataset.merge(graph_seeds[seed], on=["ym", "node"], validate="one_to_one")
            train, test = frame.split.eq("train"), frame.split.eq("test")
            for name, (features, station_only) in variants.items():
                print(f"  Fit {target} / {name} / seed={seed}", flush=True)
                model, probabilities = fit_predict(
                    frame, target, train, test, features, settings, seed, station_only
                )
                metrics.append(
                    {
                        "target": target,
                        "model": name,
                        "seed": seed,
                        **evaluate(
                            frame.loc[test, target], probabilities, settings["classification_threshold"]
                        ),
                    }
                )
                predictions.extend(
                    prediction_records(frame.loc[test], target, name, seed, probabilities, settings)
                )
                if seed == settings["seed"]:
                    joblib.dump(
                        {
                            "pipeline": model,
                            "target": target,
                            "features": features,
                            "threshold": settings["classification_threshold"],
                            "train_months": sorted(frame.loc[train, "ym"].unique()),
                            "label_version": "calendar_v1",
                            "graph_requirement": "same online embedding coordinate history required",
                        },
                        model_dir / f"{target}__{name}.joblib",
                    )
                    names = model.named_steps["features"].get_feature_names_out()
                    for feature, value in zip(names, model.named_steps["model"].feature_importances_):
                        importance.append(
                            {
                                "target": target,
                                "model": name,
                                "feature": feature,
                                "impurity_importance": value,
                            }
                        )
                    # One validation period wholly before the untouched final test. No tuning on test.
                    val = frame.ym.ge(settings["validation_start"]) & train
                    fit = frame.ym.lt(settings["validation_start"])
                    _, vp = fit_predict(frame, target, fit, val, features, settings, seed, station_only)
                    validation.append(
                        {
                            "target": target,
                            "model": name,
                            **evaluate(frame.loc[val, target], vp, settings["classification_threshold"]),
                        }
                    )
    metrics = pd.DataFrame(metrics)
    predictions = pd.DataFrame(predictions)
    csv(metrics, out / "metrics_by_seed.csv")
    csv(predictions, out / "test_predictions.csv")
    csv(pd.DataFrame(importance), out / "rf_impurity_importance.csv")
    csv(pd.DataFrame(validation), out / "validation_metrics.csv")
    summary = (
        metrics.groupby(["target", "model"])
        .agg(
            seeds=("seed", "size"),
            f1_mean=("f1", "mean"),
            f1_std=("f1", "std"),
            recall_mean=("recall", "mean"),
            precision_mean=("precision", "mean"),
            roc_auc_mean=("roc_auc", "mean"),
            average_precision_mean=("average_precision", "mean"),
            samples=("n", "first"),
            positives=("positives", "first"),
        )
        .reset_index()
    )
    csv(summary, out / "model_comparison.csv")
    ensembles = predictions.groupby(["target", "model", "ym", "ym_next", "node"], as_index=False).agg(
        actual=("actual", "first"), probability=("probability", "mean")
    )
    ensembles["predicted"] = ensembles.probability.ge(settings["classification_threshold"]).astype(int)
    ensembles["outcome"] = np.select(
        [
            (ensembles.actual.eq(1) & ensembles.predicted.eq(1)),
            (ensembles.actual.eq(0) & ensembles.predicted.eq(1)),
            (ensembles.actual.eq(1) & ensembles.predicted.eq(0)),
        ],
        ["TP", "FP", "FN"],
        default="TN",
    )
    csv(ensembles, out / "ensemble_predictions.csv")
    intervals, monthly = [], []
    for (target, name), g in ensembles.groupby(["target", "model"]):
        intervals.append(
            {
                "target": target,
                "model": name,
                **evaluate(g.actual, g.probability, settings["classification_threshold"]),
                **month_bootstrap(g, settings["seed"]),
            }
        )
        for ym, sub in g.groupby("ym"):
            k = int(np.ceil(len(sub) * settings["top_fraction"]))
            top = sub.sort_values(["probability", "node"], ascending=[False, True]).head(k)
            monthly.append(
                {
                    "target": target,
                    "model": name,
                    "ym": ym,
                    **evaluate(sub.actual, sub.probability, settings["classification_threshold"]),
                    "recall_at_top20_alert_budget": top.actual.sum() / max(1, sub.actual.sum()),
                }
            )
    csv(pd.DataFrame(intervals), out / "ensemble_metrics_month_bootstrap.csv")
    csv(pd.DataFrame(monthly), out / "metrics_by_test_month.csv")
    # Prediction samples use predeclared RF_WIP and graph counterpart, not whichever wins test.
    examples = (
        ensembles[ensembles.model.isin(["RF_WIP", "RF_WIP_graph_n2v"])]
        .sort_values(["target", "model", "outcome", "ym", "node"])
        .groupby(["target", "model", "outcome"])
        .head(3)
    )
    csv(examples, out / "prediction_examples.csv")
    # Predeclared operational illustration using the WIP-only baseline, not test-selected best model.
    alerts = ensembles[ensembles.model.eq("RF_WIP") & ensembles.target.eq("y_surge_next")].copy()
    alerts = alerts.sort_values(["ym", "probability", "node"], ascending=[True, False, True])
    alerts["alert_rank"] = alerts.groupby("ym").cumcount() + 1
    alerts["alert_budget"] = (
        alerts.groupby("ym").node.transform("size").mul(settings["top_fraction"]).apply(np.ceil)
    )
    alerts["review_alert"] = alerts.probability.ge(
        settings["classification_threshold"]
    ) & alerts.alert_rank.le(alerts.alert_budget)
    alerts["owner"] = "Kế hoạch sản xuất + phụ trách công đoạn + QC khi liên quan"
    alerts["proposed_action"] = (
        "Review stock age, routing and defect causes; prioritize only within validated resource/QC constraints"
    )
    alerts["policy_status"] = "Illustrative fixed alert rule; operational impact not measured"
    # Ground truth columns retained in evaluation artifacts; deployment view excludes future outcomes.
    csv(alerts.drop(columns=["actual", "outcome"]), out / "alert_review_policy.csv")
    walk_forward(ctx, dataset)
    json_out(
        {
            "protocol": "Fixed hyperparameters, chronological validation; final held-out feature months from 2020-07",
            "threshold": settings["classification_threshold"],
            "seed_repeats": seeds,
            "seed_mean": "Mean per-seed score; std measures algorithm randomness, not generalization uncertainty",
            "ensemble": "Separate evaluation of seed-averaged probabilities",
            "confidence_intervals": "95% percentile bootstrap of whole test months; few dependent months, exploratory only",
            "primary_target": "y_surge_next",
            "secondary_target": "y_top20_next",
            "availability_assumption": "WIP at t available at end t; BOM snapshot known; no current rework/scrap",
            "station_only": "Diagnostic of learning persistent station identity; same stations appear in train/test",
            "generalization": "Future months at known stations, conditional on snapshot topology; not unseen factories/stations",
            "importance": "RF impurity importance is descriptive and biased toward continuous/high-cardinality features",
        },
        out / "evaluation_protocol.json",
    )
    plot_forecast(ctx, summary, ensembles)
    return summary


def prediction_records(frame, target, name, seed, score, settings):
    records = []
    for (_, row), probability in zip(frame.iterrows(), score):
        records.append(
            {
                "target": target,
                "model": name,
                "seed": seed,
                "ym": row.ym,
                "ym_next": row.ym_next,
                "node": row.node,
                "actual": int(row[target]),
                "probability": float(probability),
                "predicted": int(probability >= settings["classification_threshold"]),
            }
        )
    return records


def walk_forward(ctx, data):
    settings = ctx.config["experiment"]
    rows = []
    for target in TARGETS:
        for month in sorted(data.loc[data.split.eq("test"), "ym"].unique()):
            # Refit as labels become available, distinct from the fixed holdout experiment.
            train = data.ym_next.le(month) & data.ym.lt(month)
            test = data.ym.eq(month)
            _, score = fit_predict(data, target, train, test, BASE_FEATURES, settings, settings["seed"])
            rows.append(
                {
                    "target": target,
                    "prediction_cutoff": month,
                    "model": "RF_WIP_expanding",
                    "training_rows": int(train.sum()),
                    **evaluate(data.loc[test, target], score, settings["classification_threshold"]),
                }
            )
    csv(pd.DataFrame(rows), ctx.directory("forecast") / "walk_forward_baseline.csv")


def plot_forecast(ctx, summary, predictions):
    plt = plot_setup()
    out = ctx.directory("figures")
    for target in TARGETS:
        sub = summary[summary.target.eq(target)].sort_values("f1_mean")
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.barh(sub.model, sub.f1_mean, xerr=sub.f1_std.fillna(0), color="#277da8")
        ax.set(
            xlim=(0, 1),
            xlabel="F1 trung bình; thanh sai số = độ lệch chuẩn giữa seed",
            title=f"Dự báo trên tháng giữ lại — {target}",
        )
        save_plot(fig, out / f"04_models_{target}")
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
        for model in ["RF_WIP", "RF_WIP_graph_n2v"]:
            g = predictions[predictions.target.eq(target) & predictions.model.eq(model)]
            fpr, tpr, _ = roc_curve(g.actual, g.probability)
            precision, recall, _ = precision_recall_curve(g.actual, g.probability)
            axes[0].plot(fpr, tpr, label=model)
            axes[1].plot(recall, precision, label=model)
        axes[0].plot([0, 1], [0, 1], "--", color="gray")
        axes[0].set(xlabel="False positive rate", ylabel="True positive rate", title="ROC — ensemble 5 seed")
        axes[1].axhline(g.actual.mean(), linestyle="--", color="gray", label="Tỷ lệ positive")
        axes[1].set(xlabel="Recall", ylabel="Precision", title="Precision–Recall")
        for ax in axes:
            ax.legend(fontsize=8)
        save_plot(fig, out / f"05_curves_{target}")
        fig, axes = plt.subplots(1, 2, figsize=(9, 4))
        for ax, model in zip(axes, ["RF_WIP", "RF_WIP_graph_n2v"]):
            g = predictions[predictions.target.eq(target) & predictions.model.eq(model)]
            matrix = confusion_matrix(g.actual, g.predicted, labels=[0, 1])
            ax.imshow(matrix, cmap="Blues")
            for (i, j), value in np.ndenumerate(matrix):
                ax.text(j, i, str(value), ha="center", va="center")
            ax.set(xticks=[0, 1], yticks=[0, 1], xlabel="Dự báo", ylabel="Thực tế", title=model)
        save_plot(fig, out / f"06_confusion_{target}")
