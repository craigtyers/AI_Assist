# Quickstart

## Resume Tomorrow

```bash
cd /Users/craigtyers/Projects/AI/expert
RAG_HOST=0.0.0.0 RAG_PORT=8088 python3 app.py
```

Open Open WebUI:

- http://localhost:3000

Use tool:

- `Recite Repo RAG`

If Open WebUI is not running yet:

```bash
docker start open-webui
```

## Quick Checks

In another terminal:

```bash
curl -s http://127.0.0.1:8088/health
```

Expected:

- JSON response with `"ok": true`
- `repos` contains all 3 repos

Optional if tool is missing in Open WebUI:

```bash
OPENWEBUI_TOKEN='your-bearer-token' python3 scripts/register_openwebui_tool.py
```
