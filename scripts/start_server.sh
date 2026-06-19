#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

# Defaults are overrideable: `RAG_HOST=127.0.0.1 ./scripts/start_server.sh`
export RAG_HOST="${RAG_HOST:-0.0.0.0}"
export RAG_PORT="${RAG_PORT:-5000}"
export RAG_REPO_PATHS="${RAG_REPO_PATHS:-/Users/craigtyers/Projects/AI/toolbar_backend_api/recite-api:/Users/craigtyers/Projects/AI/toolbar_frontend/recite-toolbar:/Users/craigtyers/Projects/AI/toolbar_launcher/Recite.toolbar.launcher}"

cd "$ROOT_DIR"

echo "Starting RAG server with:"
echo "  RAG_HOST=$RAG_HOST"
echo "  RAG_PORT=$RAG_PORT"
echo "  RAG_REPO_PATHS=$RAG_REPO_PATHS"

exec python3 app.py
