"""
title: Recite Repo RAG Tool
author: Craig + Codex
version: 1.0.0
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        rag_base_url: str = Field(
            default="http://host.docker.internal:8088",
            description="Base URL for the local Recite RAG API",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self.valves.rag_base_url.rstrip('/')}{path}"
        req = urllib.request.Request(
            url,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": f"HTTP {exc.code}: {detail}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"RAG request failed: {exc}"}

    def search_repo_code(self, query: str, k: int = 6) -> str:
        """
        Search indexed Recite repositories and return matching code chunks.

        :param query: Natural language or keyword query to search in indexed repos.
        :param k: Maximum number of matching chunks to return (1-20).
        :return: Formatted search results with file paths and line ranges.
        """
        k = max(1, min(int(k), 20))
        data = self._post_json("/api/search", {"query": query, "k": k})
        if not data.get("ok"):
            return f"Search failed: {data.get('error', 'unknown error')}"

        hits = data.get("hits", [])
        if not hits:
            return "No matching code chunks found."

        lines = []
        for i, hit in enumerate(hits, start=1):
            src = f"{hit['repo']}/{hit['rel_path']}:{hit['start_line']}-{hit['end_line']}"
            src_type = hit.get("source_type", "code")
            preview = hit.get("content", "").strip()
            if len(preview) > 700:
                preview = preview[:700] + "\n..."
            lines.append(f"[{i}] ({src_type}) {src}\n{preview}")

        return "\n\n".join(lines)

    def ask_repo_codebase(self, question: str, k: int = 6) -> str:
        """
        Ask a question about Recite repos using retrieval-augmented generation.

        :param question: Question about code behavior, architecture, or implementation.
        :param k: Number of retrieved chunks to ground the answer (1-20).
        :return: Grounded answer and cited source locations.
        """
        k = max(1, min(int(k), 20))
        data = self._post_json("/api/chat", {"question": question, "k": k})
        if not data.get("ok"):
            return f"RAG chat failed: {data.get('error', 'unknown error')}"

        answer = data.get("answer", "").strip() or "(no answer returned)"
        sources = data.get("sources", [])

        if not sources:
            return answer

        src_lines = [
            f"- {s['repo']}/{s['rel_path']}:{s['start_line']}-{s['end_line']}"
            for s in sources
        ]
        return f"{answer}\n\nSources:\n" + "\n".join(src_lines)
