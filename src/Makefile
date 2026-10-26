export UV_CACHE_DIR := $(CURDIR)/.uv-cache
export MPLCONFIGDIR := $(CURDIR)/.mpl-cache
export XDG_CACHE_HOME := $(CURDIR)/.cache

.PHONY: sync test check run quick audit demo verify
sync:
	uv sync --locked
test:
	uv run --locked pytest -q
check:
	uv run --locked ruff check bpmn_project tests scripts
run:
	uv run --locked congtyx all
quick:
	uv run --locked congtyx all --quick
audit:
	uv run --locked congtyx audit
demo:
	uv run --locked python scripts/execute_demo.py
verify:
	uv run --locked python scripts/verify_outputs.py
