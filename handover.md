# Handover

## Date

- June 15, 2026

## What Is Working

- Local RAG service implemented in `app.py` with endpoints:
  - `GET /health`
  - `POST /api/index`
  - `POST /api/search`
  - `POST /api/chat`
- Indexing currently includes 3 repos:
  - `/Users/craigtyers/Projects/AI/toolbar_backend_api/recite-api`
  - `/Users/craigtyers/Projects/AI/toolbar_frontend/recite-toolbar`
  - `/Users/craigtyers/Projects/AI/toolbar_launcher/Recite.toolbar.launcher`
- Open WebUI tool integration implemented:
  - Tool ID: `recite_repo_rag_tool`
  - Tool name: `Recite Repo RAG`
  - Tool code source: `openwebui_tools/recite_repo_rag_tool.py`
- Prompt behavior is baked into `rag/ollama_client.py` for RAG responses.

## Known Constraints

- Retrieval is lexical (SQLite FTS/BM25), not vector embeddings.
- Ollama embeddings endpoint currently reports disabled (`start with --embeddings`).
- For Docker Open WebUI to call local RAG API, run RAG server on `0.0.0.0`.

## Resume Commands

Start RAG API:

```bash
cd /Users/craigtyers/Projects/AI/expert
RAG_HOST=0.0.0.0 RAG_PORT=8088 python3 app.py
```

If needed, start Open WebUI container:

```bash
docker start open-webui
```

Quick health check:

```bash
curl -s http://127.0.0.1:8088/health
```

## If Tool Needs Re-Registering

```bash
cd /Users/craigtyers/Projects/AI/expert
OPENWEBUI_TOKEN='your-bearer-token' python3 scripts/register_openwebui_tool.py
```

## Suggested Next Improvements

1. Speed profile patch (reduce `k`, context truncation, `num_predict`, keep-alive).
2. Optional vector retrieval upgrade once Ollama embeddings are enabled.
3. Add lightweight logging/metrics for request timing and retrieval hit quality.
