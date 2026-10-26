"""Process discovery and two explicitly different levels of conformance evidence."""

from __future__ import annotations

from collections import defaultdict

import networkx as nx
import pandas as pd

from .common import csv, json_out


def next_observable(graph, start, kinds):
    """Traverse gateways/events only; never skip a required task.

    This is a structural possibility test. XOR guards and data values are not evaluated.
    """
    found, seen, pending = set(), set(), list(graph.successors(start))
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        if kinds[node] in {"task", "intermediateCatchEvent", "callActivity"}:
            found.add(node)
        else:
            pending.extend(graph.successors(node))
    return found


def structural_conformance(ctx, events, nodes, edges):
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes.node_id)
    graph.add_edges_from(zip(edges.source, edges.target))
    kinds = nodes.set_index("node_id").kind.to_dict()
    labels = nodes.set_index("node_id").label.to_dict()
    candidates = defaultdict(set)
    for node, label in labels.items():
        candidates[label].add(node)
    allowed = {node: next_observable(graph, node, kinds) for node in graph}
    rows, coverage = [], []
    for case, g in events[events.include_control].groupby("case_id", sort=False):
        previous, active = None, set()
        for row in g.itertuples():
            current = candidates[row.bpmn_activity]
            if previous is None:
                status, reachable = "first_observation_prefix_unknown", current
            elif not active or not current:
                status, reachable = "unknown_mapping_or_previous_deviation", current
            else:
                reachable = set().union(*(allowed[node] for node in active)) & current
                status = "structurally_possible" if reachable else "requires_missing_or_different_step"
            rows.append(
                {
                    "case_id": case,
                    "previous_event_id": previous.event_id if previous else None,
                    "event_id": row.event_id,
                    "source_row": row.source_row,
                    "previous_activity": previous.bpmn_activity if previous else None,
                    "activity": row.bpmn_activity,
                    "status": status,
                    "candidate_node_ids": "|".join(sorted(current)),
                    "reachable_candidate_ids": "|".join(sorted(reachable)),
                    "outcome": row.outcome,
                }
            )
            # Resume locally after a deviation; do not present the result as a global accepting run.
            active = reachable or current
            previous = row
        coverage.append(
            {
                "case_id": case,
                "first_activity": g.bpmn_activity.iloc[0],
                "last_activity": g.bpmn_activity.iloc[-1],
                "complete_trace_confirmed": False,
                "reason": "No externally validated case-open/case-close coverage; full-trace acceptance not asserted",
            }
        )
    out = ctx.directory("mining")
    result = pd.DataFrame(rows)
    csv(result, out / "structural_diagnostics.csv")
    csv(result[result.status.eq("requires_missing_or_different_step")], out / "structural_deviations.csv")
    csv(pd.DataFrame(coverage), out / "trace_coverage.csv")
    return result


def create_event_log(events):
    from pm4py.objects.log.obj import Event, EventLog, Trace

    log = EventLog()
    for case, group in events[events.include_control].groupby("case_id", sort=False):
        trace = Trace(attributes={"concept:name": str(case)})
        for row in group.itertuples():
            trace.append(
                Event(
                    {
                        "concept:name": row.bpmn_activity,
                        "time:timestamp": row.end_time.to_pydatetime(),
                        "org:resource": row.resource,
                        "event_id": row.event_id,
                        "source_row": int(row.source_row),
                    }
                )
            )
        log.append(trace)
    return log


def mine(ctx, events, nodes, edges):
    import shutil

    import pm4py

    out = ctx.directory("mining")
    diagnostics = structural_conformance(ctx, events, nodes, edges)
    log = create_event_log(events)
    pm4py.write_xes(log, str(out / "observed_log.xes"), show_progress_bar=False)
    results = []
    for name, discover in [
        ("inductive", lambda: pm4py.discover_petri_net_inductive(log, noise_threshold=0.2)),
        ("alpha", lambda: pm4py.discover_petri_net_alpha(log)),
    ]:
        print(f"  Discover/replay: {name}", flush=True)
        net, initial, final = discover()
        pm4py.write_pnml(net, initial, final, str(out / f"{name}.pnml"))
        fitness = pm4py.fitness_token_based_replay(log, net, initial, final)
        precision = pm4py.precision_token_based_replay(log, net, initial, final)
        results.append(
            {
                "model": name,
                "places": len(net.places),
                "transitions": len(net.transitions),
                "arcs": len(net.arcs),
                **fitness,
                "token_precision": precision,
                "evaluation_scope": "descriptive, discovered and replayed on same 8 traces; not generalization",
            }
        )
        if name == "inductive":
            bpmn = pm4py.convert_to_bpmn(net, initial, final)
            pm4py.write_bpmn(
                bpmn, str(out / "discovered_inductive.bpmn"), auto_layout=bool(shutil.which("dot"))
            )
        # DOT is portable; rendered SVG additionally generated only when Graphviz is installed.
        from pm4py.visualization.petri_net import visualizer

        visual = visualizer.apply(net, initial, final)
        (out / f"{name}.dot").write_text(visual.source, encoding="utf-8")
        if shutil.which("dot"):
            visual.format = "svg"
            visual.render(filename=name, directory=str(out), cleanup=True)
    csv(pd.DataFrame(results), out / "discovery_quality.csv")
    # Full-model token replay is diagnostic only: partial logs and duplicate labels can lower fitness.
    print("  Token replay against supplied flattened BPMN", flush=True)
    bpmn = pm4py.read_bpmn(str(ctx.data_dir / "BPMN" / "Tong the BPMN.bpmn"))
    net, initial, final = pm4py.convert_to_petri_net(bpmn)
    pm4py.write_pnml(net, initial, final, str(out / "supplied_model.pnml"))
    from pm4py.algo.conformance.tokenreplay import algorithm as token_replay

    replay = token_replay.apply(
        log, net, initial, final, parameters={"show_progress_bar": False, "disable_variants": True}
    )
    replay_rows = []
    for trace, result in zip(log, replay):
        replay_rows.append(
            {
                "case_id": trace.attributes["concept:name"],
                **{
                    k: result.get(k)
                    for k in [
                        "trace_is_fit",
                        "trace_fitness",
                        "missing_tokens",
                        "consumed_tokens",
                        "remaining_tokens",
                        "produced_tokens",
                    ]
                },
            }
        )
    csv(pd.DataFrame(replay_rows), out / "supplied_model_token_replay.csv")
    json_out(
        {
            "structural_counts": diagnostics.status.value_counts().to_dict(),
            "discovery": results,
            "conformance_interpretation": [
                "Structural diagnostics preserve source event order and candidate task IDs across duplicate labels",
                "They test control-flow possibility only, not guards, quantities, class layers, or global accepting runs",
                "After a deviation the local check resumes, so a structurally_possible pair is not proof of full conformance",
                "Full token replay is descriptive; prefixes/suffixes are unknown and duplicate labels are ambiguous",
                "Timer 72h is checked separately; untimed Petri-net replay cannot enforce its duration",
                "No fitness score here establishes correct execution at the company or out-of-sample accuracy",
            ],
        },
        out / "summary.json",
    )
