#!/usr/bin/env bash
# T3 Code worktree setup script for llm-dojo-scoring.
#
# Registered as the project's runOnWorktreeCreate setup script so every
# agent worktree starts with an importable, tested checkout. Idempotent and
# fast: prefers uv (the repo ships uv.lock), falls back to venv + pip.
#
# Usage:  bash scripts/t3-setup.sh   (from the repo root)
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

PY_RUN=()
if command -v uv >/dev/null 2>&1; then
  echo "[t3-setup] using uv"
  uv sync --extra dev --quiet 2>/dev/null || uv pip install -e ".[dev]" --quiet
  PY_RUN=(uv run python)
else
  echo "[t3-setup] uv not found; using venv + pip"
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip --quiet
  python -m pip install -e ".[dev]" --quiet
  PY_RUN=(python)
fi

# Smoke test: import + version + release governor dry-run.
echo "[t3-setup] smoke test"
"${PY_RUN[@]}" -c "import llm_dojo_scoring; print('dojo', llm_dojo_scoring.__version__)"
"${PY_RUN[@]}" scripts/release.py status --json >/dev/null

echo "[t3-setup] OK"
