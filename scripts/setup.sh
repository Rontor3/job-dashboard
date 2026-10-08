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

MODEL="${OLLAMA_MODEL:-qwen3:14b}"
if ! command -v ollama >/dev/null; then
    if [[ "$(uname)" == "Darwin" ]] && command -v brew >/dev/null; then
        brew install --cask ollama-app
    else
        echo "Install Ollama from https://ollama.com, then re-run this script." >&2
        exit 1
    fi
fi
if ! curl -fs -m 2 localhost:11434/api/version >/dev/null; then
    if [[ "$(uname)" == "Darwin" ]]; then open -a Ollama; else (ollama serve >/dev/null 2>&1 &); fi
    for _ in $(seq 1 30); do curl -fs -m 2 localhost:11434/api/version >/dev/null && break; sleep 2; done
fi
ollama pull "$MODEL"

command -v direnv >/dev/null && direnv allow

echo "Setup complete. Run tests: uv run pytest -q"
echo "Optional, manual: MacTeX / TeX Live for résumé PDFs; data/answer_style/ingredients.json (personal, gitignored)."
