#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
command -v npm >/dev/null || { echo "Node 18+ / npm is required" >&2; exit 1; }

uv sync
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers"
uv run playwright install chromium
npm --prefix frontend ci
npm --prefix frontend run build

echo "Setup complete. Run tests: uv run pytest -q"
echo "Still manual: Ollama + model (see README), optional MacTeX for résumé PDFs."
