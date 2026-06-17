# Server Layout and Deployment

This project is the RAG app/control plane.  
Your 3 source repos should stay as separate clones and be mounted via `RAG_REPO_PATHS`.

## Recommended directory layout

```text
/opt/ai-assist                              # this repo
/opt/rag-sources/recite-api
/opt/rag-sources/recite-toolbar
/opt/rag-sources/Recite.toolbar.launcher
```

## 1) Clone repos on server

```bash
git clone git@github.com:craigtyers/AI_Assist.git /opt/ai-assist
git clone <recite-api-url> /opt/rag-sources/recite-api
git clone <recite-toolbar-url> /opt/rag-sources/recite-toolbar
git clone <launcher-url> /opt/rag-sources/Recite.toolbar.launcher
```

## 2) Run the app with explicit repo paths

```bash
cd /opt/ai-assist
export RAG_REPO_PATHS="/opt/rag-sources/recite-api:/opt/rag-sources/recite-toolbar:/opt/rag-sources/Recite.toolbar.launcher"
export RAG_HOST=0.0.0.0
export RAG_PORT=8088
python3 app.py
```

## Ollama setup (required)

The app uses Ollama for generation. Current default model is `qwen3:8b`.

### Install Ollama

Use official install docs for your server OS:  
https://ollama.com/download

### Start Ollama service

```bash
ollama serve
```

### Pull required model

```bash
ollama pull qwen3:8b
```

### Verify Ollama and model

```bash
curl -s http://127.0.0.1:11434/api/tags
curl -s http://127.0.0.1:11434/api/generate \
  -d '{"model":"qwen3:8b","prompt":"Say OK","stream":false}'
```

## 3) Build/rebuild index

Either use UI `Reindex repos` or call API directly:

```bash
curl -s -X POST http://127.0.0.1:8088/api/index \
  -H 'Content-Type: application/json' \
  -d '{}'
```

## 4) Health and smoke checks

```bash
curl -s http://127.0.0.1:8088/health
curl -s -X POST http://127.0.0.1:8088/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"toolbar changelog recent changes","k":8,"docs_only":true}'
```

## 5) Update flow

### Update app code

```bash
cd /opt/ai-assist
git pull
```

Then restart app process.

### Update source repos

```bash
cd /opt/rag-sources/recite-api && git pull
cd /opt/rag-sources/recite-toolbar && git pull
cd /opt/rag-sources/Recite.toolbar.launcher && git pull
```

Then trigger reindex.

## Notes

- Do not copy the 3 source repos into this repo.
- `data/rag.db` is local runtime data and should not be committed.
- If brand rotation is used, ensure `web/brand_names.json` is present and app is restarted after updates.
