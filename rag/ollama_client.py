from __future__ import annotations

import json
import urllib.error
import urllib.request

from rag.config import (
    DEFAULT_MODEL,
    EMBED_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_GENERATE_TIMEOUT_SEC,
)


def ollama_generate(prompt: str, model: str | None = None, temperature: float = 0.1) -> str:
    payload = {
        "model": model or DEFAULT_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_GENERATE_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {msg}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to call Ollama: {exc}") from exc

    parsed = json.loads(body)
    return parsed.get("response", "").strip()


def ollama_embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    if not texts:
        return []

    payload = {
        "model": model or EMBED_MODEL,
        "input": texts,
    }
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/embed",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama embed HTTP {exc.code}: {msg}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to call Ollama embed API: {exc}") from exc

    parsed = json.loads(body)
    embeddings = parsed.get("embeddings")
    if not isinstance(embeddings, list):
        raise RuntimeError("Ollama embed API returned no embeddings array")
    return embeddings


def build_rag_prompt(question: str, contexts: list[dict]) -> str:
    context_blocks = []
    for i, ctx in enumerate(contexts, start=1):
        src = f"{ctx['repo']}/{ctx['rel_path']}:{ctx['start_line']}-{ctx['end_line']}"
        context_blocks.append(f"[{i}] Source: {src}\n{ctx['content']}")

    joined_context = "\n\n".join(context_blocks)
    return (
        "You are an expert Support Engineer for Recite Me.\n\n"
        "Context:\n"
        "- Recite Me provides an accessibility toolbar for client websites.\n"
        "- The toolbar can be integrated on any website using a client key.\n\n"
        "Response rules:\n"
        "- If the question is not genuinely about Recite Me support/products/implementation, politely refuse and ask for a Recite-related question.\n"
        "- Use only the provided context. Never invent behavior, APIs, settings, or facts.\n"
        "- If context is missing or ambiguous, explicitly say 'Insufficient evidence in retrieved sources' and state what to verify.\n"
        "- If sources disagree, call out the conflict and do not guess.\n"
        "- Keep tone professional and client-safe.\n"
        "- Always provide two sections when possible:\n"
        "  1) Non-technical explanation\n"
        "  2) Technical explanation\n"
        "- Include concrete citations inline like [1], [2].\n"
        "- Use valid Markdown formatting only.\n"
        "- For code snippets, always use fenced code blocks with triple backticks, e.g. ```html ... ``` or ```js ... ```.\n"
        "- Never use malformed code fences like ``html or unmatched backticks.\n"
        "- Add a short 'Recommended next steps' section when helpful.\n"
        "- If no useful sources are provided, return only:\n"
        "  Insufficient evidence in retrieved sources.\n"
        "  What to verify: <short checklist>\n\n"
        f"Question:\n{question}\n\n"
        f"Retrieved context:\n{joined_context}\n\n"
        "Answer:"
    )
