from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from rag.config import ROOT

KB_DIR = ROOT / "KnowledgeBase"
KB_INDEX_JSON = KB_DIR / "index.json"
KB_INDEX_HTML = KB_DIR / "index.html"


def ensure_kb_dir() -> None:
    KB_DIR.mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "kb-article"


def _load_index() -> list[dict[str, Any]]:
    if not KB_INDEX_JSON.exists():
        return []
    try:
        return json.loads(KB_INDEX_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _save_index(items: list[dict[str, Any]]) -> None:
    items = sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)
    KB_INDEX_JSON.write_text(json.dumps(items, indent=2), encoding="utf-8")

    rows = []
    for item in items:
        title = escape(str(item.get("title", "Untitled")))
        file_name = escape(str(item.get("file", "")))
        created = escape(str(item.get("created_at", "")))
        question = escape(str(item.get("question", "")))
        rows.append(
            f'<li><a href="/kb/{file_name}">{title}</a>'
            f'<div class="meta">{created}</div>'
            f'<div class="q">{question}</div></li>'
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Knowledge Base</title>
  <style>
    body {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; margin: 0; background: #ecf1f5; color: #18222c; }}
    .wrap {{ max-width: 1040px; margin: 0 auto; padding: 24px; }}
    .kb-head {{ background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%); border: 1px solid #d4deea; border-radius: 14px; padding: 18px; margin-bottom: 14px; }}
    .kicker {{ margin: 0 0 6px; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: #2b5e8c; font-weight: 700; }}
    h1 {{ margin: 0; font-size: 30px; color: #173d5e; }}
    h1 a {{ color: inherit; text-decoration: none; }}
    h1 a:hover {{ text-decoration: underline; }}
    .subtitle {{ margin: 8px 0 0; color: #4f6478; }}
    ul {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; }}
    li {{ background: #fff; border: 1px solid #d8dde4; border-radius: 12px; padding: 12px 14px; }}
    a {{ color: #0b6bcb; font-weight: 700; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .meta {{ font-size: 12px; color: #5e6b77; margin-top: 4px; }}
    .q {{ margin-top: 7px; font-size: 14px; color: #2b3a49; }}
    .footer-links {{ margin-top: 14px; display: flex; justify-content: flex-end; gap: 16px; flex-wrap: wrap; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="kb-head">
      <p class="kicker">Recite Me</p>
      <h1><a href="/kb">Knowledge Base</a></h1>
      <p class="subtitle">Reusable answers, implementation notes, and guidance.</p>
    </header>
    <ul>
      {"".join(rows) if rows else "<li>No KB articles yet.</li>"}
    </ul>
    <footer class="footer-links">
      <a href="/">Ask something new</a>
      <a href="/kb/new">Create KB article</a>
    </footer>
  </div>
</body>
</html>
"""
    KB_INDEX_HTML.write_text(html, encoding="utf-8")


def _normalize_answer(answer: str) -> str:
    return (answer or "").replace("\r\n", "\n").strip()


def _normalize_branding(text: str) -> str:
    # Standardize brand casing in user-provided KB content.
    return re.sub(r"\brecite\s+me\b", "Recite Me", text or "", flags=re.IGNORECASE)


def _build_structured_answer(
    non_technical: str,
    technical: str,
    recommended_steps: str,
    what_to_verify: str = "",
) -> str:
    parts = [
        "### Non-technical explanation",
        _normalize_answer(non_technical) or "(not provided)",
        "",
        "### Technical explanation",
        _normalize_answer(technical) or "(not provided)",
        "",
        "### Recommended next steps",
        _normalize_answer(recommended_steps) or "(not provided)",
    ]
    verify = _normalize_answer(what_to_verify)
    if verify:
        parts.extend(["", "### What to verify", verify])
    return "\n".join(parts).strip()


def _answer_markdown_to_html(answer: str) -> str:
    text = _normalize_answer(answer)

    code_blocks: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        code = match.group(2) or ""
        html = f"<pre><code>{escape(code)}</code></pre>"
        code_blocks.append(html)
        return f"@@CODEBLOCK_{len(code_blocks)-1}@@"

    text = re.sub(r"```([a-zA-Z0-9_-]+)?\n([\s\S]*?)```", stash_code, text)
    text = re.sub(r"`([^`]+)`", lambda m: f"<code>{escape(m.group(1))}</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)

    lines = text.split("\n")
    out: list[str] = []
    in_ul = False
    in_ol = False
    paragraph: list[str] = []

    def flush_p() -> None:
        nonlocal paragraph
        if paragraph:
            out.append(f"<p>{' '.join(paragraph)}</p>")
            paragraph = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_p()
            close_lists()
            continue

        if line.startswith("@@CODEBLOCK_") and line.endswith("@@"):
            flush_p()
            close_lists()
            idx = int(line.replace("@@CODEBLOCK_", "").replace("@@", ""))
            out.append(code_blocks[idx])
            continue

        if line.startswith("### "):
            flush_p()
            close_lists()
            out.append(f"<h3>{line[4:]}</h3>")
            continue

        m_ol = re.match(r"^\d+\.\s+(.+)$", line)
        if m_ol:
            flush_p()
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{m_ol.group(1)}</li>")
            continue

        m_ul = re.match(r"^[-*]\s+(.+)$", line)
        if m_ul:
            flush_p()
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{m_ul.group(1)}</li>")
            continue

        paragraph.append(line)

    flush_p()
    close_lists()
    return "\n".join(out)


def kb_exists_for_question(question: str) -> dict[str, Any]:
    ensure_kb_dir()
    slug = slugify(question)
    path = KB_DIR / f"{slug}.html"
    return {"exists": path.exists(), "slug": slug, "file": path.name}


def create_kb_article(question: str, answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    ensure_kb_dir()
    question = _normalize_branding((question or "").strip())
    if not question:
        raise ValueError("question is required")
    answer = _normalize_branding(_normalize_answer(answer))
    if not answer:
        raise ValueError("answer is required")

    check = kb_exists_for_question(question)
    if check["exists"]:
        return {"ok": False, "exists": True, "slug": check["slug"], "file": check["file"]}

    slug = check["slug"]
    file_name = f"{slug}.html"
    out_path = KB_DIR / file_name
    created_at = datetime.now(timezone.utc).isoformat()
    title = question.rstrip("?").strip() or "Untitled"

    src_rows = []
    for s in sources or []:
        repo = escape(str(s.get("repo", "")))
        rel = escape(str(s.get("rel_path", "")))
        start = escape(str(s.get("start_line", "")))
        end = escape(str(s.get("end_line", "")))
        if repo and rel:
            href = "/api/source?" + urlencode(
                {
                    "repo": str(s.get("repo", "")),
                    "path": str(s.get("rel_path", "")),
                    "start": str(s.get("start_line", "")),
                    "end": str(s.get("end_line", "")),
                }
            )
            src_rows.append(
                f'<li><a href="{escape(href)}" target="_blank" rel="noopener noreferrer">{repo}/{rel}:{start}-{end}</a></li>'
            )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escape(title)} | Knowledge Base</title>
  <style>
    body {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; margin: 0; background: #ecf1f5; color: #18222c; }}
    .wrap {{ max-width: 1040px; margin: 0 auto; padding: 24px; }}
    .kb-head {{ background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%); border: 1px solid #d4deea; border-radius: 14px; padding: 18px; margin-bottom: 14px; }}
    .kicker {{ margin: 0 0 6px; font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: #2b5e8c; font-weight: 700; }}
    .kb-head h1 {{ margin: 0; font-size: 30px; color: #173d5e; }}
    .kb-head h1 a {{ color: inherit; text-decoration: none; }}
    .kb-head h1 a:hover {{ text-decoration: underline; }}
    .kb-head p {{ margin: 8px 0 0; color: #4f6478; }}
    .card {{ background: #ffffff; border: 1px solid #d8dde4; border-radius: 14px; padding: 20px; box-shadow: 0 8px 20px rgba(17, 44, 73, 0.05); }}
    .title {{ margin: 0 0 10px; color: #123756; }}
    .meta {{ color: #5e6b77; font-size: 13px; margin-bottom: 14px; }}
    .q {{ padding: 12px; background: #f4f9ff; border: 1px solid #d6e4f3; border-radius: 10px; }}
    .a {{ margin-top: 16px; }}
    .a h2 {{ font-size: 22px; margin: 0 0 12px; color: #173d5e; }}
    .a h3 {{ font-size: 18px; margin-top: 24px; margin-bottom: 8px; color: #0d62a8; letter-spacing: 0.01em; }}
    .a p {{ line-height: 1.7; color: #1f2d3a; margin-top: 10px; }}
    .a ul, .a ol {{ margin-top: 8px; margin-bottom: 10px; }}
    .a li {{ margin-bottom: 7px; line-height: 1.65; }}
    .a pre {{
      background: #0f1720;
      color: #f8fafc;
      border: 1px solid #2b3744;
      padding: 16px 18px;
      border-radius: 10px;
      overflow-x: auto;
      margin-top: 12px;
      margin-bottom: 12px;
    }}
    .a pre code {{
      background: transparent;
      border: 0;
      padding: 0;
      color: #f8fafc;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 15px;
      line-height: 1.7;
    }}
    .a code {{
      background: #eef3f8;
      border: 1px solid #dbe4ee;
      border-radius: 6px;
      padding: 1px 5px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 14px;
      color: #1b2b3a;
    }}
    .refs {{ margin-top: 22px; border-top: 1px solid #d9e3ee; padding-top: 14px; }}
    .refs h3 {{ margin: 0 0 8px; color: #305a7d; }}
    .refs a {{ color: #0b6bcb; text-decoration: none; }}
    .refs a:hover {{ text-decoration: underline; }}
    .footer-links {{ margin-top: 14px; display: flex; justify-content: flex-end; gap: 16px; flex-wrap: wrap; }}
    .footer-links a {{ color: #0b6bcb; text-decoration: none; font-weight: 700; }}
    .footer-links a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="kb-head">
      <p class="kicker">Recite Me</p>
      <h1><a href="/kb">Knowledge Base</a></h1>
      <p>Practical guidance and implementation patterns.</p>
    </header>
    <div class="card">
      <h2 class="title">{escape(title)}</h2>
      <div class="meta">Created: {escape(created_at)}</div>
      <div class="q"><strong>Question:</strong> {escape(question)}</div>
      <div class="a">
        <h2>Answer</h2>
        {_answer_markdown_to_html(answer)}
      </div>
      <div class="refs">
        <h3>References</h3>
        <ul>
          {"".join(src_rows) if src_rows else "<li>No references captured.</li>"}
        </ul>
      </div>
    </div>
    <footer class="footer-links">
      <a href="/kb">Back to index</a>
      <a href="/kb/new">Create KB article</a>
      <a href="/">Ask something new</a>
    </footer>
  </div>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")

    items = _load_index()
    items.append(
        {
            "slug": slug,
            "file": file_name,
            "title": title,
            "question": question,
            "created_at": created_at,
            "sources_count": len(sources or []),
        }
    )
    _save_index(items)
    return {"ok": True, "exists": False, "slug": slug, "file": file_name}


def create_structured_kb_article(
    question: str,
    non_technical: str,
    technical: str,
    recommended_steps: str,
    what_to_verify: str = "",
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    answer = _build_structured_answer(non_technical, technical, recommended_steps, what_to_verify)
    return create_kb_article(question, answer, sources or [])
