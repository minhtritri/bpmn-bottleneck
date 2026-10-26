"""Portable graph visuals; exported coordinates make every plot inspectable."""

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from .common import csv, json_out, plot_setup, save_plot


def graph_visuals(ctx, dataset, graph_seeds, sheets):
    plt = plot_setup()
    seed = ctx.config["experiment"]["seed"]
    frame = graph_seeds[seed]
    month = dataset.ym.max()
    sub = frame[frame.ym.eq(month)].merge(
        sheets["D1 Danh mục trạm"], left_on="node", right_on="activity_name", validate="one_to_one"
    )
    dimensions = [f"n2v_{i}" for i in range(ctx.config["embedding"]["dimensions"])]
    pca = PCA(n_components=2)
    coordinates = pca.fit_transform(sub[dimensions])
    sub["pca_x"], sub["pca_y"] = coordinates[:, 0], coordinates[:, 1]
    csv(
        sub[["ym", "node", "activity_id", "department", "pca_x", "pca_y"]],
        ctx.directory("forecast") / "embedding_pca_coordinates.csv",
    )
    json_out(
        {
            "month": month,
            "seed": seed,
            "explained_variance_ratio": pca.explained_variance_ratio_,
            "interpretation": "Descriptive projection; separation by colors is not a supervised performance metric",
        },
        ctx.directory("forecast") / "embedding_pca_contract.json",
    )
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = plt.get_cmap("tab20")
    for i, (department, group) in enumerate(sub.groupby("department")):
        ax.scatter(group.pca_x, group.pca_y, color=colors(i), s=48, label=department, alpha=0.85)
        for row in group.itertuples():
            ax.annotate(
                row.activity_id, (row.pca_x, row.pca_y), xytext=(3, 3), textcoords="offset points", fontsize=6
            )
    ax.set(
        xlabel=f"PC1 ({pca.explained_variance_ratio_[0]:.1%})",
        ylabel=f"PC2 ({pca.explained_variance_ratio_[1]:.1%})",
        title=f"Node2Vec 16D → PCA — {month}, seed {seed}; màu là phòng ban được cung cấp",
    )
    ax.legend(loc="center left", bbox_to_anchor=(1, 0.5), fontsize=7)
    save_plot(fig, ctx.directory("figures") / "08_node2vec_projection")

    weights = pd.read_csv(ctx.directory("forecast") / "derived_edge_weights.csv")
    weights = weights[weights.ym.eq(month)]
    names = sub.set_index("node").activity_id.to_dict()
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(names))
    graph.add_edges_from((r.source, r.target, {"weight": r.weight}) for r in weights.itertuples())
    pos = nx.spring_layout(graph, seed=seed, weight=None, iterations=150)
    fig, ax = plt.subplots(figsize=(12, 8))
    nx.draw_networkx_edges(
        graph, pos, ax=ax, alpha=0.3, arrowsize=9, width=0.7, connectionstyle="arc3,rad=0.06", node_size=440
    )
    nx.draw_networkx_nodes(graph, pos, ax=ax, node_size=440, node_color="#cfe5ef", edgecolors="#277da8")
    nx.draw_networkx_labels(graph, pos, labels=names, font_size=6, ax=ax)
    ax.set_title(f"Routing snapshot trong thực nghiệm — {len(graph)} trạm, {len(graph.edges)} cạnh BOM")
    ax.axis("off")
    save_plot(fig, ctx.directory("figures") / "09_routing_graph")


def process_visuals(ctx):
    plt = plot_setup()
    out = ctx.directory("process")
    dfg = pd.read_csv(out / "dfg.csv")
    labels = sorted(set(dfg.previous_bpmn_activity).union(dfg.bpmn_activity))
    ids = {label: f"T{i + 1:02d}" for i, label in enumerate(labels)}
    csv(
        pd.DataFrame([{"plot_id": short, "activity": label} for label, short in ids.items()]),
        out / "dfg_plot_legend.csv",
    )
    # A frequency-filtered DFG is a visual summary, not a replacement executable model.
    shown = dfg.sort_values("frequency", ascending=False).head(30)
    graph = nx.DiGraph()
    for row in shown.itertuples():
        graph.add_edge(ids[row.previous_bpmn_activity], ids[row.bpmn_activity], frequency=row.frequency)
    pos = nx.spring_layout(graph, seed=42, iterations=150)
    fig, ax = plt.subplots(figsize=(11, 7))
    widths = [1 + np.log1p(graph[u][v]["frequency"]) / 2 for u, v in graph.edges]
    nx.draw_networkx(
        graph,
        pos,
        ax=ax,
        node_size=1000,
        node_color="#d8e9f2",
        font_size=9,
        width=widths,
        arrowsize=15,
        connectionstyle="arc3,rad=0.08",
    )
    nx.draw_networkx_edge_labels(
        graph, pos, edge_labels={(u, v): graph[u][v]["frequency"] for u, v in graph.edges}, font_size=7, ax=ax
    )
    ax.set_title("DFG — 30 cặp có tần suất cao nhất; tra tên task trong dfg_plot_legend.csv")
    ax.axis("off")
    save_plot(fig, ctx.directory("figures") / "10_observed_dfg")
