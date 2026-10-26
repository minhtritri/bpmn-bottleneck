"""Shared paths, serialization and source-level provenance."""

from __future__ import annotations

import hashlib
import json
import platform
import tomllib
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Context:
    data_dir: Path
    out: Path
    config: dict

    @property
    def workbook(self):
        return self.data_dir / "CongTyX_Event log.xlsx"

    def directory(self, name):
        path = self.out / name
        path.mkdir(parents=True, exist_ok=True)
        return path


def make_context(data_dir=None, output=None, config=None):
    config_path = Path(config or ROOT / "config.toml").resolve()
    with config_path.open("rb") as handle:
        settings = tomllib.load(handle)
    return Context(
        Path(data_dir or ROOT.parent).resolve(), Path(output or ROOT / "outputs").resolve(), settings
    )


def csv(frame, path):
    frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.10g")


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (Path, pd.Timestamp, pd.Period)):
        return str(value)
    return value


def json_out(value, path):
    path.write_text(
        json.dumps(_clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(ctx):
    files = sorted(
        p
        for p in ctx.data_dir.rglob("*")
        if p.is_file() and ROOT not in p.parents and p.suffix in {".xlsx", ".bpmn", ".docx", ".pdf"}
    )
    return {
        "project": "BPMN bottleneck diagnosis and conditional WIP forecasting — Công ty X",
        "python": platform.python_version(),
        "versions": {
            p: version(p)
            for p in [
                "pandas",
                "openpyxl",
                "numpy",
                "scipy",
                "scikit-learn",
                "networkx",
                "pm4py",
                "gensim",
                "matplotlib",
            ]
        },
        "sources": [{"path": str(p.relative_to(ctx.data_dir)), "sha256": sha256(p)} for p in files],
        "configuration": ctx.config,
        "project_files": [
            {"path": str(p.relative_to(ROOT)), "sha256": sha256(p)}
            for p in sorted([*ROOT.glob("bpmn_project/*.py"), ROOT / "uv.lock", ROOT / "pyproject.toml"])
            if p.exists()
        ],
        "scope": {
            "MES": "8 purposively selected serial histories; endpoints are not all completed cases",
            "monthly": "D1/D2/D4 supplied snapshots; upstream company exports and original generation code absent",
            "graph": "D2 BOM edges only, treated as an available routing snapshot; historical revision date unknown",
            "simulation": "conditional scenarios, not measured causal effects or a calibrated capacity model",
        },
    }


def plot_setup():
    import os

    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mpl-cache"))
    os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 120,
            "savefig.dpi": 180,
        }
    )
    return plt


def save_plot(fig, path):
    import matplotlib.pyplot as plt

    fig.tight_layout()
    fig.savefig(path.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
