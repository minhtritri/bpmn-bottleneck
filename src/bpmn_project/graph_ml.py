"""BOM snapshot graphs, causal WIP weights, second-order Node2Vec and online alignment.

The graph is an associative feature generator, not a BPMN execution engine.
Node2Vec uses an undirected projection; directed metrics are retained separately.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
from gensim.models import Word2Vec
from scipy.linalg import orthogonal_procrustes

from .common import csv, json_out

GRAPH_FEATURES = ["in_weight", "out_weight", "pagerank", "in_degree", "out_degree"]


def transition_probabilities(graph, previous, current, candidates, p, q):
    if p <= 0 or q <= 0:
        raise ValueError("p and q must be positive")
    weights = []
    for target in candidates:
        bias = (
            1.0
            if previous is None
            else (1 / p if target == previous else 1.0 if graph.has_edge(previous, target) else 1 / q)
        )
        weights.append(graph[current][target].get("weight", 1.0) * bias)
    values = np.asarray(weights, dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Node2Vec requires finite positive edge weights")
    return values / values.sum()


def node2vec(graph, order, config, seed):
    rng = np.random.default_rng(seed)
    neighbors = {node: sorted(graph.neighbors(node)) for node in order}
    # Precompute second-order distributions; only random sampling happens in the inner loop.
    distributions = {}
    for current in order:
        choices = neighbors[current]
        if not choices:
            continue
        for previous in [None, *choices]:
            distributions[previous, current] = transition_probabilities(
                graph, previous, current, choices, config["p"], config["q"]
            )
    walks = []
    for _ in range(config["walks_per_node"]):
        for start in rng.permutation(order):
            walk = [str(start)]
            previous, current = None, start
            for _ in range(config["walk_length"] - 1):
                choices = neighbors[current]
                if not choices:
                    break
                # searchsorted avoids the high overhead of rng.choice for short distributions.
                probs = distributions[previous, current]
                index = min(int(np.searchsorted(np.cumsum(probs), rng.random())), len(choices) - 1)
                target = choices[index]
                walk.append(str(target))
                previous, current = current, target
            walks.append(walk)
    model = Word2Vec(
        sentences=walks,
        vector_size=config["dimensions"],
        window=config["window"],
        min_count=1,
        sg=1,
        workers=1,
        epochs=config["epochs"],
        seed=seed,
        sorted_vocab=1,
        sample=0,
        hashfxn=stable_hash,
    )
    matrix = np.array([model.wv[str(n)] for n in order])
    matrix = matrix - matrix.mean(axis=0)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def stable_hash(text):
    import hashlib

    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "little")


def align_embedding(current, reference):
    """Orthogonal alignment to previous observed month only; no future reference fit."""
    rotation, _ = orthogonal_procrustes(current, reference)
    aligned = current @ rotation
    return aligned, float(np.linalg.norm(aligned - reference) / np.sqrt(len(current)))


def graphs_by_month(panel, routing, config):
    order = sorted(panel.node.unique())
    allowed = set(order)
    # Exclude edges supported only by the 8 MES traces; no future trace-frequency input.
    topology = routing[(routing.n_bom > 0) & routing.src.isin(allowed) & routing.dst.isin(allowed)]
    graphs, metrics, edge_rows = {}, [], []
    for month in sorted(panel.month.unique()):
        history = panel[(panel.month <= month) & (panel.month > month - config["history_months"])]
        # Average available snapshots only, never a fabricated zero for a missing month.
        wip = history.groupby("node").wip.mean().fillna(0).to_dict()
        graph = nx.DiGraph()
        graph.add_nodes_from(order)
        for row in topology.itertuples():
            weight = 1 + 0.5 * (np.log1p(wip.get(row.src, 0)) + np.log1p(wip.get(row.dst, 0)))
            graph.add_edge(row.src, row.dst, weight=float(weight))
            edge_rows.append(
                {
                    "ym": str(month),
                    "source": row.src,
                    "target": row.dst,
                    "weight": weight,
                    "weight_semantics": "WIP context, not observed transition count",
                }
            )
        rank = nx.pagerank(graph, weight="weight")
        for node in order:
            metrics.append(
                {
                    "ym": str(month),
                    "node": node,
                    "in_weight": graph.in_degree(node, weight="weight"),
                    "out_weight": graph.out_degree(node, weight="weight"),
                    "pagerank": rank[node],
                    "in_degree": graph.in_degree(node),
                    "out_degree": graph.out_degree(node),
                }
            )
        # Reciprocal edges sum their weights; this policy is explicit, deterministic.
        undirected = nx.Graph()
        undirected.add_nodes_from(order)
        for source, target, attrs in graph.edges(data=True):
            prev = undirected.get_edge_data(source, target, {}).get("weight", 0)
            undirected.add_edge(source, target, weight=prev + attrs["weight"])
        graphs[str(month)] = undirected
    return order, graphs, pd.DataFrame(metrics), pd.DataFrame(edge_rows)


def graph_features(ctx, panel, sheets):
    out = ctx.directory("forecast")
    cfg = ctx.config["embedding"]
    order, graphs, metrics, edges = graphs_by_month(panel, sheets["D2 Cạnh đồ thị"], cfg)
    csv(metrics, out / "graph_metrics.csv")
    csv(edges, out / "derived_edge_weights.csv")
    all_seeds, diagnostics = {}, []
    for seed in ctx.config["experiment"]["seeds"]:
        previous = None
        records = []
        print(f"  Node2Vec seed={seed}: {len(graphs)} monthly graphs", flush=True)
        for ym, graph in graphs.items():
            matrix = node2vec(graph, order, cfg, seed)
            error = 0.0
            if previous is not None:
                matrix, error = align_embedding(matrix, previous)
            previous = matrix.copy()
            diagnostics.append(
                {
                    "seed": seed,
                    "ym": ym,
                    "alignment_rmse": error,
                    "reference": "previous month only",
                    "isolated_nodes": len(list(nx.isolates(graph))),
                }
            )
            for node, vector in zip(order, matrix):
                records.append(
                    {"ym": ym, "node": node, **{f"n2v_{i}": float(x) for i, x in enumerate(vector)}}
                )
        embedding = pd.DataFrame(records)
        csv(embedding, out / f"node_embeddings_seed_{seed}.csv")
        all_seeds[seed] = metrics.merge(embedding, on=["ym", "node"], validate="one_to_one")
    csv(pd.DataFrame(diagnostics), out / "embedding_alignment.csv")
    json_out(
        {
            "graph_input": "D2 edges with n_bom>0, restricted to the 54 observed monthly stations",
            "historical_validity": "Conditional on snapshot topology being available before forecasting; revision dates absent",
            "edge_weight": "1 + 0.5*(log1p(mean source WIP)+log1p(mean target WIP)); trailing 3 calendar months through t",
            "excluded": [
                "D3 supplied dynamic weights",
                "D2 n_mes and n_bom counts as weights",
                "all t+1 WIP",
            ],
            "embedding": "Node2Vec second-order p/q walks + skip-gram negative sampling; undirected projection",
            "alignment": "Centered, row-normalized, sequential orthogonal Procrustes to preceding embedding; no future reference",
            "limitations": [
                "WIP-derived graph weights may duplicate baseline information",
                "Undirected embedding discards BPMN control-flow semantics",
                "Embedding is associative; cannot establish a causal bottleneck",
            ],
        },
        out / "graph_contract.json",
    )
    return all_seeds
