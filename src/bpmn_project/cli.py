"""Command-line orchestration. All numbers are generated from supplied inputs."""

from __future__ import annotations

import argparse
import time
import traceback
from datetime import UTC, datetime

import pandas as pd

from .analysis import process_analysis
from .common import ROOT, csv, json_out, make_context, sha256
from .data import prepare
from .features import build_features
from .graph_ml import graph_features
from .mining import mine
from .models import forecast
from .simulation import simulate
from .visuals import graph_visuals, process_visuals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", nargs="?", default="all", choices=["all", "audit", "analyze", "mine", "forecast", "simulate"]
    )
    parser.add_argument("--data-dir", help="Directory containing original workbook and BPMN/")
    parser.add_argument("--output", help="Output directory; original inputs are never modified")
    parser.add_argument("--config", help="TOML settings file")
    parser.add_argument(
        "--quick", action="store_true", help="Smoke run, single seed; defaults to outputs_quick/"
    )
    args = parser.parse_args()
    ctx = make_context(
        args.data_dir, args.output or (ROOT / "outputs_quick" if args.quick else None), args.config
    )
    if args.quick:
        ctx.config["experiment"].update(seeds=[42], trees=60)
        ctx.config["embedding"].update(walks_per_node=5, epochs=3)
        ctx.config["simulation"]["replications"] = 1000
    started = time.perf_counter()
    status = {
        "stage": args.stage,
        "quick": args.quick,
        "started_utc": datetime.now(UTC).isoformat(),
        "completed_steps": [],
    }
    try:
        print("[1] Read, normalize, audit workbook/BPMN", flush=True)
        events, sheets, nodes, edges = prepare(ctx)
        status["completed_steps"].append("audit")
        if args.stage in {"all", "analyze", "simulate"}:
            print("[2] Descriptive process analysis", flush=True)
            process_analysis(ctx, events, sheets)
            process_visuals(ctx)
            status["completed_steps"].append("analyze")
        if args.stage in {"all", "mine"}:
            print("[3] Discovery and conformance diagnostics", flush=True)
            mine(ctx, events, nodes, edges)
            status["completed_steps"].append("mine")
        if args.stage in {"all", "forecast"}:
            print("[4] Calendar-aware feature/label reconstruction", flush=True)
            panel, dataset = build_features(ctx, sheets)
            print("[5] Graph metrics and online-aligned Node2Vec", flush=True)
            graph_seeds = graph_features(ctx, panel, sheets)
            print("[6] Temporal holdout / validation / expanding-window baseline", flush=True)
            forecast(ctx, dataset, graph_seeds)
            graph_visuals(ctx, dataset, graph_seeds, sheets)
            status["completed_steps"].append("forecast")
        if args.stage in {"all", "simulate"}:
            print("[7] Conditional improvement scenarios", flush=True)
            simulate(ctx, events, sheets)
            status["completed_steps"].append("simulate")
        status["status"] = "success"
    except Exception:
        status["status"] = "failed"
        status["error"] = traceback.format_exc()
        raise
    finally:
        status["elapsed_seconds"] = time.perf_counter() - started
        status["finished_utc"] = datetime.now(UTC).isoformat()
        json_out(status, ctx.directory("metadata") / f"run_{args.stage}.json")
    inventory = []
    for path in sorted(ctx.out.rglob("*")):
        if path.is_file() and path.name != "artifact_inventory.csv":
            entry = {
                "artifact": str(path.relative_to(ctx.out)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            if path.suffix == ".csv":
                frame = pd.read_csv(path)
                entry.update(rows=len(frame), columns=len(frame.columns))
            inventory.append(entry)
    csv(pd.DataFrame(inventory), ctx.directory("metadata") / "artifact_inventory.csv")
    print(f"Done in {status['elapsed_seconds']:.1f}s → {ctx.out}", flush=True)


if __name__ == "__main__":
    main()
