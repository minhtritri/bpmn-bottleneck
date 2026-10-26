"""Execute the demo with a local uv kernel; never install a global kernelspec."""

import json
import os
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mpl-cache"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))
os.environ.setdefault("IPYTHONDIR", str(ROOT / ".jupyter" / "ipython"))
kernel_dir = ROOT / ".jupyter" / "kernels" / "bpmn-uv"
kernel_dir.mkdir(parents=True, exist_ok=True)
(kernel_dir / "kernel.json").write_text(
    json.dumps(
        {
            "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "BPMN — uv",
            "language": "python",
        }
    ),
    encoding="utf-8",
)
os.environ["JUPYTER_PATH"] = str(ROOT / ".jupyter")
os.environ["JUPYTER_RUNTIME_DIR"] = str(ROOT / ".jupyter" / "runtime")
notebook = nbformat.read(ROOT / "demo.ipynb", as_version=4)
client = NotebookClient(
    notebook, timeout=180, kernel_name="bpmn-uv", resources={"metadata": {"path": str(ROOT)}}
)
client.execute()
target = ROOT / "outputs" / "demo_executed.ipynb"
nbformat.write(notebook, target)
print(f"Executed {len(notebook.cells)} cells → {target}")
