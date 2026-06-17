# Local AI + RAG Experiment

This workspace now includes:
- Ollama model serving (`qwen3:8b`)
- Open WebUI for general chat UI
- A local RAG API + web console over your private repos

Current implementation status (June 15, 2026):
- RAG indexes 3 private repos (`recite-api`, `recite-toolbar`, `Recite.toolbar.launcher`)
- Open WebUI tool integration is implemented (`Recite Repo RAG`)
- Recite support-engineer prompt behavior is baked into `rag/ollama_client.py` for RAG answers

## Repo paths used for RAG

Detected repositories:
- `/Users/craigtyers/Projects/AI/toolbar_backend_api/recite-api`
- `/Users/craigtyers/Projects/AI/toolbar_frontend/recite-toolbar`
- `/Users/craigtyers/Projects/AI/toolbar_launcher/Recite.toolbar.launcher`

If these ever move, set `RAG_REPO_PATHS` before indexing.
Example:

```bash
export RAG_REPO_PATHS="/abs/path/repo-one:/abs/path/repo-two"
```

## 1. Ollama model setup

```bash
ollama pull qwen3:8b
ollama run qwen3:8b
```

## 2. Start Open WebUI with Docker

```bash
docker run -d \
  -p 3000:8080 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart unless-stopped \
  openwebui/open-webui:latest
```

Open:
- http://localhost:3000

## 3. Build the local RAG index

From this folder (`/Users/craigtyers/Projects/AI/expert`):

```bash
python3 -m rag.indexer
```

This creates `data/rag.db` with chunked code/docs + FTS index.

Optional (recommended) for hybrid retrieval:

```bash
export RAG_ENABLE_EMBEDDINGS=1
export RAG_EMBED_MODEL=nomic-embed-text
python3 -m rag.indexer
```

## 4. Run the RAG API + web UI

```bash
python3 app.py
```

Open:
- http://127.0.0.1:8088

If Open WebUI (Docker) needs to call this API as a tool, run it on all interfaces:

```bash
RAG_HOST=0.0.0.0 RAG_PORT=8088 python3 app.py
```

## API endpoints

- `GET /health`
- `POST /api/index` (rebuild index)
- `POST /api/search`
- `POST /api/chat`

### Example calls

```bash
curl -s -X POST http://127.0.0.1:8088/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Stats Interactions toolbar","k":3}'
```

```bash
curl -s -X POST http://127.0.0.1:8088/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"Where is toolbar interaction tracking implemented?","k":6}'
```

## Notes

- Retrieval now supports hybrid mode:
  - lexical (SQLite FTS/BM25)
  - semantic (Ollama embeddings, when `RAG_ENABLE_EMBEDDINGS=1`)
  - reciprocal-rank fusion + lightweight reranking
- If Ollama embeddings are disabled on your daemon, indexing and retrieval automatically fallback to lexical mode.
- `ask_repo_codebase` responses use a baked-in Recite support style (non-technical + technical framing when context allows).

### Tuning env vars (optional)

```bash
# Retrieval fusion
export RAG_HYBRID_ALPHA=0.65           # lexical weight (0..1)
export RAG_RETRIEVAL_CANDIDATES=40     # candidate pool before rerank

# Chunking
export RAG_CHUNK_CHARS=1400
export RAG_MIN_CHUNK_CHARS=450
export RAG_CHUNK_OVERLAP=200

# Source weighting
export RAG_DOC_SOURCE_BOOST=1.12
export RAG_RAGDOC_SOURCE_BOOST=1.35
export RAG_KB_SOURCE_BOOST=1.45
export RAG_CODE_SOURCE_BOOST=1.0

# Guardrails
export RAG_MIN_EVIDENCE_HITS=2
```

## Open WebUI Tool Integration

Files added:
- `openwebui_tools/recite_repo_rag_tool.py` (tool code uploaded into Open WebUI)
- `scripts/register_openwebui_tool.py` (create/update tool via API)

### Register tool (one command)

```bash
cd /Users/craigtyers/Projects/AI/expert
OPENWEBUI_EMAIL='your@email.com' OPENWEBUI_PASSWORD='your-password' \
python3 scripts/register_openwebui_tool.py
```

Or with token:

```bash
OPENWEBUI_TOKEN='your-bearer-token' python3 scripts/register_openwebui_tool.py
```

### Use inside Open WebUI

1. Open http://localhost:3000
2. Go to Workspace -> Tools and confirm `Recite Repo RAG` exists
3. In chat, enable that tool for the conversation/model
4. Ask questions like:
   - `Use ask_repo_codebase to explain how launcher auto-launch works`
   - `Use search_repo_code for "toolbar launch url-fragment"`

If calls fail, set tool valve `rag_base_url` to `http://host.docker.internal:8088` and ensure RAG API is running with `RAG_HOST=0.0.0.0`.

## Resume Docs

- See `quickstart.md` for the shortest startup flow
- See `handover.md` for full status, known constraints, and next options
