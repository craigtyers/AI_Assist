from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from rag.config import ROOT

KB_DIR = ROOT / "KnowledgeBase"
KB_INDEX_JSON = KB_DIR / "index.json"
KB_INDEX_HTML = KB_DIR / "index.html"
KB_PENDING_DIR = ROOT / "KB_pending"
KB_PENDING_INDEX_JSON = KB_PENDING_DIR / "index.json"
SECTION_KEYS = (
    "non_technical",
    "technical",
    "recommended_steps",
    "what_to_verify",
)


def ensure_kb_dir() -> None:
    KB_DIR.mkdir(parents=True, exist_ok=True)


def ensure_kb_pending_dir() -> None:
    KB_PENDING_DIR.mkdir(parents=True, exist_ok=True)


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


def _save_pending_index(items: list[dict[str, Any]]) -> None:
    items = sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)
    KB_PENDING_INDEX_JSON.write_text(json.dumps(items, indent=2), encoding="utf-8")


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


def normalize_structured_sections(sections: dict[str, Any] | None) -> dict[str, str]:
    base = {
        "non_technical": "",
        "technical": "",
        "recommended_steps": "",
        "what_to_verify": "",
    }
    if not isinstance(sections, dict):
        return base
    for key in SECTION_KEYS:
        base[key] = _normalize_answer(str(sections.get(key, "")))
    return base


def extract_structured_sections(answer: str) -> dict[str, str]:
    text = _normalize_answer(answer)
    text = re.sub(
        r"^\s*\*\*\s*(Non-technical(?: explanation)?|Technical(?: explanation)?|Recommended(?: next)? steps|What to verify)\s*\*\*\s*:?\s*$",
        lambda m: f"### {m.group(1)}",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    heading_re = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
    matches = list(heading_re.finditer(text))
    if not matches:
        return {
            "non_technical": "",
            "technical": text,
            "recommended_steps": "",
            "what_to_verify": "",
        }

    out = {
        "non_technical": "",
        "technical": "",
        "recommended_steps": "",
        "what_to_verify": "",
    }

    def section_key(title: str) -> str | None:
        t = title.strip().lower()
        if "non-technical" in t or "non technical" in t:
            return "non_technical"
        if "recommended" in t and "step" in t:
            return "recommended_steps"
        if "verify" in t:
            return "what_to_verify"
        if "technical" in t:
            return "technical"
        return None

    for i, match in enumerate(matches):
        key = section_key(match.group(1))
        if key is None:
            continue
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = _normalize_answer(text[start:end])
        out[key] = body

    if not any(out.values()):
        out["technical"] = text
    return out


def _sections_to_answer(sections: dict[str, Any] | None) -> str:
    normalized = normalize_structured_sections(sections)
    return _build_structured_answer(
        non_technical=normalized["non_technical"],
        technical=normalized["technical"],
        recommended_steps=normalized["recommended_steps"],
        what_to_verify=normalized["what_to_verify"],
    )


def _html_fragment_to_text(fragment: str) -> str:
    text = fragment or ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li\s*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(ul|ol)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<pre[^>]*>", "\n```\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</pre\s*>", "\n```\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</h3\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_structured_sections_from_article_html(path: Path) -> dict[str, str]:
    try:
        html = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return normalize_structured_sections({})

    m = re.search(
        r'<div class="a">.*?<h2>Answer</h2>(.*?)</div>\s*<div class="refs">',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return normalize_structured_sections({})
    answer_html = m.group(1)

    heading_re = re.compile(r"<h3>(.*?)</h3>", flags=re.IGNORECASE | re.DOTALL)
    matches = list(heading_re.finditer(answer_html))
    if not matches:
        body = _html_fragment_to_text(answer_html)
        return normalize_structured_sections({"technical": body})

    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        heading = _html_fragment_to_text(match.group(1)).lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(answer_html)
        body = _html_fragment_to_text(answer_html[start:end])
        if "non-technical" in heading or "non technical" in heading:
            sections["non_technical"] = body
        elif "recommended" in heading and "step" in heading:
            sections["recommended_steps"] = body
        elif "verify" in heading:
            sections["what_to_verify"] = body
        elif "technical" in heading:
            sections["technical"] = body
    return normalize_structured_sections(sections)


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


def pending_kb_exists_for_question(question: str) -> dict[str, Any]:
    ensure_kb_pending_dir()
    slug = slugify(question)
    path = KB_PENDING_DIR / f"{slug}.html"
    return {"exists": path.exists(), "slug": slug, "file": path.name}


def _load_pending_index() -> list[dict[str, Any]]:
    if not KB_PENDING_INDEX_JSON.exists():
        return []
    try:
        return json.loads(KB_PENDING_INDEX_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def create_kb_article(
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    sections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_kb_dir()
    question = _normalize_branding((question or "").strip())
    if not question:
        raise ValueError("question is required")
    answer = _normalize_branding(_normalize_answer(answer))
    if not answer:
        raise ValueError("answer is required")
    section_data = normalize_structured_sections(sections or extract_structured_sections(answer))

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
            "sources": sources or [],
            "sections": section_data,
        }
    )
    _save_index(items)
    return {"ok": True, "exists": False, "slug": slug, "file": file_name}


def _write_pending_article_html(
    *,
    out_path: Path,
    title: str,
    question: str,
    answer: str,
    created_at: str,
    sources: list[dict[str, Any]],
) -> None:
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
  <title>{escape(title)} | KB Pending</title>
  <style>
    body {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; margin: 0; background: #ecf1f5; color: #18222c; }}
    .wrap {{ max-width: 1040px; margin: 0 auto; padding: 24px; }}
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
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h2 class="title">{escape(title)}</h2>
      <div class="meta">Status: Pending admin approval | Created: {escape(created_at)}</div>
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
  </div>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def create_pending_kb_article(
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    sections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_kb_pending_dir()
    question = _normalize_branding((question or "").strip())
    if not question:
        raise ValueError("question is required")
    answer_norm = _normalize_branding(_normalize_answer(answer))
    if not answer_norm:
        raise ValueError("answer is required")
    section_data = normalize_structured_sections(sections or extract_structured_sections(answer_norm))
    answer_clean = _normalize_branding(_sections_to_answer(section_data))

    published_check = kb_exists_for_question(question)
    if published_check["exists"]:
        return {
            "ok": False,
            "exists": True,
            "published": True,
            "pending": False,
            "slug": published_check["slug"],
            "file": published_check["file"],
            "url": f"/kb/{published_check['file']}",
        }

    check = pending_kb_exists_for_question(question)
    if check["exists"]:
        return {
            "ok": False,
            "exists": True,
            "published": False,
            "pending": True,
            "slug": check["slug"],
            "file": check["file"],
        }

    slug = check["slug"]
    file_name = f"{slug}.html"
    out_path = KB_PENDING_DIR / file_name
    created_at = datetime.now(timezone.utc).isoformat()
    title = question.rstrip("?").strip() or "Untitled"

    _write_pending_article_html(
        out_path=out_path,
        title=title,
        question=question,
        answer=answer_clean,
        created_at=created_at,
        sources=sources,
    )

    items = _load_pending_index()
    items.append(
        {
            "slug": slug,
            "file": file_name,
            "title": title,
            "question": question,
            "created_at": created_at,
            "sources_count": len(sources or []),
            "sources": sources or [],
            "sections": section_data,
        }
    )
    _save_pending_index(items)
    return {"ok": True, "exists": False, "pending": True, "slug": slug, "file": file_name}


def list_pending_kb_articles() -> list[dict[str, Any]]:
    ensure_kb_pending_dir()
    items = _load_pending_index()
    changed = False
    for i, item in enumerate(items):
        sections = normalize_structured_sections(item.get("sections", {}))
        if any(sections.values()):
            continue
        file_name = str(item.get("file", ""))
        if not file_name:
            continue
        path = KB_PENDING_DIR / file_name
        if not path.exists():
            continue
        recovered = extract_structured_sections_from_article_html(path)
        if any(recovered.values()):
            item_copy = dict(item)
            item_copy["sections"] = recovered
            items[i] = item_copy
            changed = True
    if changed:
        _save_pending_index(items)
    return items


def list_published_kb_articles() -> list[dict[str, Any]]:
    ensure_kb_dir()
    return _load_index()


def get_pending_kb_article(slug: str) -> dict[str, Any]:
    ensure_kb_pending_dir()
    slug_norm = slugify(slug or "")
    for item in _load_pending_index():
        if item.get("slug") == slug_norm:
            return item
    raise FileNotFoundError(f"Pending KB index entry not found for slug: {slug_norm}")


def update_pending_kb_article_sections(slug: str, sections: dict[str, Any]) -> dict[str, Any]:
    ensure_kb_pending_dir()
    slug_norm = slugify(slug or "")
    if not slug_norm:
        raise ValueError("slug is required")

    items = _load_pending_index()
    idx = next((i for i, item in enumerate(items) if item.get("slug") == slug_norm), -1)
    if idx < 0:
        raise FileNotFoundError(f"Pending KB index entry not found for slug: {slug_norm}")

    item = dict(items[idx])
    file_name = str(item.get("file", f"{slug_norm}.html"))
    question = str(item.get("question", ""))
    title = str(item.get("title", slug_norm))
    created_at = str(item.get("created_at", datetime.now(timezone.utc).isoformat()))
    sources = item.get("sources", [])
    if not isinstance(sources, list):
        sources = []

    section_data = normalize_structured_sections(sections)
    answer = _sections_to_answer(section_data)
    out_path = KB_PENDING_DIR / file_name
    _write_pending_article_html(
        out_path=out_path,
        title=title,
        question=question,
        answer=answer,
        created_at=created_at,
        sources=sources,
    )

    item["sections"] = section_data
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    items[idx] = item
    _save_pending_index(items)
    return {
        "ok": True,
        "slug": slug_norm,
        "file": file_name,
        "sections": section_data,
    }


def approve_pending_kb_article(slug: str) -> dict[str, Any]:
    ensure_kb_dir()
    ensure_kb_pending_dir()
    slug = slugify(slug or "")
    if not slug:
        raise ValueError("slug is required")

    pending_file = f"{slug}.html"
    pending_path = KB_PENDING_DIR / pending_file
    if not pending_path.exists():
        raise FileNotFoundError(f"Pending KB article not found for slug: {slug}")

    published_path = KB_DIR / pending_file
    if published_path.exists():
        raise FileExistsError(f"Published KB article already exists for slug: {slug}")

    pending_items = _load_pending_index()
    pending_item = next((i for i in pending_items if i.get("slug") == slug), None)
    if pending_item is None:
        raise FileNotFoundError(f"Pending KB index entry not found for slug: {slug}")

    shutil.move(str(pending_path), str(published_path))

    pending_items = [i for i in pending_items if i.get("slug") != slug]
    _save_pending_index(pending_items)

    published_items = _load_index()
    published_items.append(
        {
            "slug": slug,
            "file": pending_item.get("file", pending_file),
            "title": pending_item.get("title", slug),
            "question": pending_item.get("question", ""),
            "created_at": pending_item.get("created_at", datetime.now(timezone.utc).isoformat()),
            "sources_count": int(pending_item.get("sources_count", 0)),
            "sources": pending_item.get("sources", []) if isinstance(pending_item.get("sources"), list) else [],
            "sections": normalize_structured_sections(pending_item.get("sections", {})),
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_index(published_items)

    return {"ok": True, "slug": slug, "file": pending_file, "url": f"/kb/{pending_file}"}


def unstage_published_kb_article(slug: str) -> dict[str, Any]:
    ensure_kb_dir()
    ensure_kb_pending_dir()
    slug_norm = slugify(slug or "")
    if not slug_norm:
        raise ValueError("slug is required")

    file_name = f"{slug_norm}.html"
    published_path = KB_DIR / file_name
    if not published_path.exists():
        raise FileNotFoundError(f"Published KB article not found for slug: {slug_norm}")

    pending_path = KB_PENDING_DIR / file_name
    if pending_path.exists():
        raise FileExistsError(f"Pending KB article already exists for slug: {slug_norm}")

    published_items = _load_index()
    published_item = next((i for i in published_items if i.get("slug") == slug_norm), None)
    if published_item is None:
        raise FileNotFoundError(f"Published KB index entry not found for slug: {slug_norm}")

    shutil.move(str(published_path), str(pending_path))
    published_items = [i for i in published_items if i.get("slug") != slug_norm]
    _save_index(published_items)

    section_data = normalize_structured_sections(published_item.get("sections", {}))
    if not any(section_data.values()):
        section_data = extract_structured_sections_from_article_html(pending_path)

    pending_items = _load_pending_index()
    pending_items.append(
        {
            "slug": slug_norm,
            "file": file_name,
            "title": str(published_item.get("title", slug_norm)),
            "question": str(published_item.get("question", "")),
            "created_at": str(published_item.get("created_at", datetime.now(timezone.utc).isoformat())),
            "sources_count": int(published_item.get("sources_count", 0)),
            "sources": published_item.get("sources", []) if isinstance(published_item.get("sources"), list) else [],
            "sections": section_data,
            "unstaged_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_pending_index(pending_items)
    return {"ok": True, "slug": slug_norm, "file": file_name}


def create_structured_kb_article(
    question: str,
    non_technical: str,
    technical: str,
    recommended_steps: str,
    what_to_verify: str = "",
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    answer = _build_structured_answer(non_technical, technical, recommended_steps, what_to_verify)
    return create_kb_article(
        question,
        answer,
        sources or [],
        sections={
            "non_technical": non_technical,
            "technical": technical,
            "recommended_steps": recommended_steps,
            "what_to_verify": what_to_verify,
        },
    )


def create_structured_pending_kb_article(
    question: str,
    non_technical: str,
    technical: str,
    recommended_steps: str,
    what_to_verify: str = "",
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    answer = _build_structured_answer(non_technical, technical, recommended_steps, what_to_verify)
    return create_pending_kb_article(question, answer, sources or [])
