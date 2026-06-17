from __future__ import annotations

import json
import re
import sqlite3
from typing import Iterable

from rag.config import DB_PATH


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def _tokens(question: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_]+", (question or "").lower()) if len(t) >= 2]


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_norm TEXT NOT NULL,
            question_tokens_json TEXT NOT NULL,
            repo TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            helpful INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def record_feedback(question: str, sources: list[dict], helpful: bool) -> int:
    question_norm = _normalize_question(question)
    if not question_norm or not sources:
        return 0

    token_json = json.dumps(_tokens(question_norm))
    rows = []
    for src in sources[:16]:
        repo = str(src.get("repo", "")).strip()
        rel_path = str(src.get("rel_path", "")).strip()
        if not repo or not rel_path:
            continue
        rows.append((question_norm, token_json, repo, rel_path, 1 if helpful else 0))

    if not rows:
        return 0

    conn = sqlite3.connect(DB_PATH)
    _ensure_schema(conn)
    conn.executemany(
        """
        INSERT INTO feedback_signals (question_norm, question_tokens_json, repo, rel_path, helpful)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def get_feedback_biases(question: str, source_keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], float]:
    source_keys = list({(r, p) for r, p in source_keys if r and p})
    if not source_keys:
        return {}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)

    clauses = ["(repo = ? AND rel_path = ?)" for _ in source_keys]
    params: list[str] = []
    for repo, rel_path in source_keys:
        params.extend([repo, rel_path])

    sql = f"""
        SELECT question_norm, question_tokens_json, repo, rel_path, helpful
        FROM feedback_signals
        WHERE {" OR ".join(clauses)}
        ORDER BY id DESC
        LIMIT 2000
    """
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    q_norm = _normalize_question(question)
    q_tokens = set(_tokens(question))
    out: dict[tuple[str, str], float] = {k: 0.0 for k in source_keys}

    for idx, row in enumerate(rows):
        key = (row["repo"], row["rel_path"])
        if key not in out:
            continue

        helpful = bool(row["helpful"])
        direction = 1.0 if helpful else -1.0
        recency_decay = max(0.35, 1.0 - (idx / 2500.0))

        if row["question_norm"] == q_norm:
            weight = 0.26
        else:
            try:
                row_tokens = set(json.loads(row["question_tokens_json"]))
            except Exception:  # noqa: BLE001
                row_tokens = set()
            overlap = (len(q_tokens & row_tokens) / max(1, len(q_tokens | row_tokens))) if q_tokens else 0.0
            if overlap >= 0.40:
                weight = 0.11
            elif overlap >= 0.20:
                weight = 0.05
            else:
                weight = 0.02

        out[key] += direction * weight * recency_decay

    for key in list(out):
        out[key] = max(-0.75, min(0.75, out[key]))
    return out
