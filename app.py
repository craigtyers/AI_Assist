from __future__ import annotations

import json
import os
import time
import traceback
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from rag.config import (
    DEFAULT_MODEL,
    MAX_PROMPT_CHARS_PER_CHUNK,
    MAX_PROMPT_CONTEXT_CHUNKS,
    MIN_EVIDENCE_HITS,
    REPO_PATHS,
    RETRY_K,
)
from rag.feedback import record_feedback
from rag.indexer import index_all_repos
from rag.kb import KB_DIR, create_kb_article, create_structured_kb_article, kb_exists_for_question
from rag.ollama_client import build_rag_prompt, ollama_generate
from rag.search import search_chunks, serialize_hits

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"


class Handler(BaseHTTPRequestHandler):
    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, (int, float)):
            return value != 0
        return False

    def _json_response(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html_response(self, content: str, status: int = 200) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _repo_map() -> dict[str, Path]:
        return {p.name: p.resolve() for p in REPO_PATHS}

    @staticmethod
    def _prepare_prompt_contexts(contexts: list[dict]) -> list[dict]:
        trimmed: list[dict] = []
        for ctx in contexts[:MAX_PROMPT_CONTEXT_CHUNKS]:
            content = str(ctx.get("content", ""))
            if len(content) > MAX_PROMPT_CHARS_PER_CHUNK:
                content = content[:MAX_PROMPT_CHARS_PER_CHUNK] + "\n...[truncated]"
            item = dict(ctx)
            item["content"] = content
            trimmed.append(item)
        return trimmed

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            self._json_response(
                {
                    "ok": True,
                    "model": DEFAULT_MODEL,
                    "repos": [str(p) for p in REPO_PATHS],
                }
            )
            return

        if parsed.path in {"/", "/index.html"}:
            index_path = WEB_ROOT / "index.html"
            content = index_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if parsed.path == "/brand_names.json":
            file_path = WEB_ROOT / "brand_names.json"
            if not file_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "Brand config not found")
                return
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if parsed.path in {"/kb", "/kb/"}:
            kb_index = KB_DIR / "index.html"
            if kb_index.exists():
                content = kb_index.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "KB index not found")
            return

        if parsed.path in {"/kb/new", "/kb/new/"}:
            create_page = WEB_ROOT / "kb_new.html"
            if not create_page.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "KB create page not found")
                return
            content = create_page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if parsed.path.startswith("/kb/"):
            rel = parsed.path[len("/kb/") :].strip()
            target = (KB_DIR / rel).resolve()
            try:
                target.relative_to(KB_DIR.resolve())
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid path")
                return
            if not target.exists() or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                return

            content = target.read_bytes()
            ctype = "text/html; charset=utf-8" if target.suffix.lower() == ".html" else "application/json; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if parsed.path == "/api/source":
            params = parse_qs(parsed.query)
            repo = (params.get("repo", [""])[0] or "").strip()
            rel_path = (params.get("path", [""])[0] or "").strip()
            start = int((params.get("start", ["1"])[0] or "1"))
            end = int((params.get("end", ["1"])[0] or "1"))

            if not repo or not rel_path:
                self.send_error(HTTPStatus.BAD_REQUEST, "repo and path are required")
                return

            repo_map = self._repo_map()
            repo_root = repo_map.get(repo)
            if repo_root is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown repo")
                return

            source_path = (repo_root / rel_path).resolve()
            try:
                source_path.relative_to(repo_root)
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid path")
                return

            if not source_path.exists() or not source_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                return

            try:
                lines = source_path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Non-text file")
                return
            except OSError:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to read file")
                return

            start = max(1, start)
            end = max(start, end)

            rendered_lines = []
            for i, line in enumerate(lines, start=1):
                cls = "hl" if start <= i <= end else ""
                rendered_lines.append(
                    f'<div class="line {cls}"><span class="ln">{i}</span><span class="tx">{escape(line)}</span></div>'
                )

            html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escape(repo)}/{escape(rel_path)}</title>
  <style>
    body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0; background: #f6f8fb; color: #18222c; }}
    .head {{ position: sticky; top: 0; background: #fff; border-bottom: 1px solid #d9e0e8; padding: 10px 14px; }}
    .meta {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; font-size: 13px; }}
    .code {{ padding: 10px 14px 22px; }}
    .line {{ white-space: pre; }}
    .line.hl {{ background: #fff6cf; }}
    .ln {{ display: inline-block; width: 60px; color: #8a96a3; user-select: none; }}
    .tx {{ color: #13202b; }}
  </style>
</head>
<body>
  <div class="head">
    <div class="meta"><strong>{escape(repo)}/{escape(rel_path)}</strong></div>
    <div class="meta">Highlighted lines: {start}-{end}</div>
  </div>
  <div class="code">
    {"".join(rendered_lines)}
  </div>
</body>
</html>"""
            self._html_response(html)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/index":
                summary = index_all_repos()
                self._json_response({"ok": True, "summary": summary})
                return

            if self.path == "/api/search":
                t0 = time.perf_counter()
                payload = self._read_json()
                query = str(payload.get("query", "")).strip()
                k = int(payload.get("k", 6))
                docs_only = self._as_bool(payload.get("docs_only", False))
                hits = search_chunks(query, k, docs_only=docs_only)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._json_response(
                    {
                        "ok": True,
                        "hits": serialize_hits(hits),
                        "docs_only": docs_only,
                        "latency_ms": latency_ms,
                    }
                )
                return

            if self.path == "/api/chat":
                t0 = time.perf_counter()
                payload = self._read_json()
                question = str(payload.get("question", "")).strip()
                k = int(payload.get("k", 6))
                retry = self._as_bool(payload.get("retry", False))
                model = str(payload.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
                docs_only = self._as_bool(payload.get("docs_only", False))

                if not question:
                    self._json_response({"ok": False, "error": "question is required"}, status=400)
                    return

                effective_k = max(k, RETRY_K) if retry else k
                hits = search_chunks(question, effective_k, docs_only=docs_only)
                contexts = serialize_hits(hits)

                min_hits = 1 if retry else MIN_EVIDENCE_HITS
                if len(contexts) < min_hits:
                    self._json_response(
                        {
                            "ok": True,
                            "answer": "Insufficient evidence in retrieved sources.\nWhat to verify: identify authoritative files or docs for this question, then re-run with more focused terms.",
                            "sources": [
                                {
                                    "repo": h["repo"],
                                    "rel_path": h["rel_path"],
                                    "start_line": h["start_line"],
                                    "end_line": h["end_line"],
                                    "source_type": h.get("source_type", "code"),
                                }
                                for h in contexts
                            ],
                            "evidence_hits": len(contexts),
                            "min_evidence_hits": min_hits,
                            "docs_only": docs_only,
                            "retry": retry,
                            "k": effective_k,
                            "latency_ms": int((time.perf_counter() - t0) * 1000),
                        }
                    )
                    return

                prompt_contexts = self._prepare_prompt_contexts(contexts)
                prompt = build_rag_prompt(question, prompt_contexts)
                answer = ollama_generate(prompt, model=model)

                self._json_response(
                    {
                        "ok": True,
                        "answer": answer,
                        "sources": [
                            {
                                "repo": h["repo"],
                                "rel_path": h["rel_path"],
                                "start_line": h["start_line"],
                                "end_line": h["end_line"],
                                "source_type": h.get("source_type", "code"),
                            }
                            for h in contexts
                        ],
                        "evidence_hits": len(contexts),
                        "min_evidence_hits": min_hits,
                        "docs_only": docs_only,
                        "retry": retry,
                        "k": effective_k,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                    }
                )
                return

            if self.path == "/api/feedback":
                payload = self._read_json()
                question = str(payload.get("question", "")).strip()
                helpful = self._as_bool(payload.get("helpful", False))
                sources = payload.get("sources", [])
                if not isinstance(sources, list):
                    self._json_response({"ok": False, "error": "sources must be a list"}, status=400)
                    return

                count = record_feedback(question, sources, helpful=helpful)
                self._json_response({"ok": True, "recorded": count, "helpful": helpful})
                return

            if self.path == "/api/kb/check":
                payload = self._read_json()
                question = str(payload.get("question", "")).strip()
                if not question:
                    self._json_response({"ok": False, "error": "question is required"}, status=400)
                    return
                check = kb_exists_for_question(question)
                self._json_response({"ok": True, **check})
                return

            if self.path == "/api/kb/create":
                payload = self._read_json()
                question = str(payload.get("question", "")).strip()
                answer = str(payload.get("answer", "")).strip()
                sources = payload.get("sources", [])
                if not isinstance(sources, list):
                    self._json_response({"ok": False, "error": "sources must be a list"}, status=400)
                    return

                result = create_kb_article(question, answer, sources)
                if result.get("exists"):
                    self._json_response(
                        {
                            "ok": True,
                            "created": False,
                            "exists": True,
                            "slug": result.get("slug"),
                            "file": result.get("file"),
                            "url": f"/kb/{result.get('file')}",
                        }
                    )
                    return
                self._json_response(
                    {
                        "ok": True,
                        "created": True,
                        "exists": False,
                        "slug": result.get("slug"),
                        "file": result.get("file"),
                        "url": f"/kb/{result.get('file')}",
                    }
                )
                return

            if self.path == "/api/kb/create-form":
                payload = self._read_json()
                question = str(payload.get("question", "")).strip()
                non_technical = str(payload.get("non_technical", "")).strip()
                technical = str(payload.get("technical", "")).strip()
                recommended_steps = str(payload.get("recommended_steps", "")).strip()
                what_to_verify = str(payload.get("what_to_verify", "")).strip()
                sources = payload.get("sources", [])
                if not isinstance(sources, list):
                    self._json_response({"ok": False, "error": "sources must be a list"}, status=400)
                    return
                if not question:
                    self._json_response({"ok": False, "error": "question is required"}, status=400)
                    return

                result = create_structured_kb_article(
                    question=question,
                    non_technical=non_technical,
                    technical=technical,
                    recommended_steps=recommended_steps,
                    what_to_verify=what_to_verify,
                    sources=sources,
                )
                if result.get("exists"):
                    self._json_response(
                        {
                            "ok": True,
                            "created": False,
                            "exists": True,
                            "slug": result.get("slug"),
                            "file": result.get("file"),
                            "url": f"/kb/{result.get('file')}",
                        }
                    )
                    return
                self._json_response(
                    {
                        "ok": True,
                        "created": True,
                        "exists": False,
                        "slug": result.get("slug"),
                        "file": result.get("file"),
                        "url": f"/kb/{result.get('file')}",
                    }
                )
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json_response({"ok": False, "error": str(exc)}, status=500)


def run() -> None:
    host = os.getenv("RAG_HOST", "127.0.0.1")
    port = int(os.getenv("RAG_PORT", "8088"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"RAG server listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
