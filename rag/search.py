from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import asdict, dataclass

from rag.config import (
    CODE_SOURCE_BOOST,
    DB_PATH,
    DOC_SOURCE_BOOST,
    EMBED_MODEL,
    ENABLE_EMBEDDINGS,
    HYBRID_ALPHA,
    KB_SOURCE_BOOST,
    MAX_EMBED_SCAN,
    RAG_DOC_SOURCE_BOOST,
    RETRIEVAL_CANDIDATES,
    RRF_K,
)
from rag.feedback import get_feedback_biases
from rag.ollama_client import ollama_embed_texts


@dataclass
class SearchHit:
    id: int
    repo: str
    rel_path: str
    start_line: int
    end_line: int
    content: str
    source_type: str
    score: float


def _tokenize(query: str) -> list[str]:
    return [tok for tok in re.findall(r"[A-Za-z0-9_]+", query.lower()) if len(tok) >= 2]


def _build_fts_query(tokens: list[str]) -> str:
    return " OR ".join(f"{tok}*" for tok in tokens)


def _expand_tokens_for_intent(tokens: list[str], query: str) -> list[str]:
    q = query.lower()
    expanded = set(tokens)

    setup_intent_terms = (
        "how do i add",
        "add the toolbar",
        "to my website",
        "bottom right",
        "accessibility tools",
    )
    if any(t in q for t in setup_intent_terms):
        expanded.update(
            {
                "launcher",
                "clientid",
                "data",
                "script",
                "floating",
                "bottom",
                "right",
                "website",
                "reciteme",
                "toolbar",
            }
        )

    tts_pronunciation_terms = (
        "tts",
        "text to speech",
        "pronunciation",
        "pronounce",
        "acronym",
        "initials",
        "reads badly",
        "read as",
    )
    if any(t in q for t in tts_pronunciation_terms):
        expanded.update(
            {
                "tts",
                "speech",
                "pronunciation",
                "pronounce",
                "acronym",
                "initialism",
                "dom",
                "word",
                "filter",
                "word_filter",
                "options",
                "reference",
                "toolbar",
            }
        )

    recent_changes_terms = (
        "recent",
        "recent changes",
        "latest",
        "what changed",
        "changelog",
        "release notes",
        "updates",
        "new in",
    )
    if any(t in q for t in recent_changes_terms):
        expanded.update(
            {
                "change",
                "changes",
                "changelog",
                "release",
                "releases",
                "notes",
                "updated",
                "update",
                "toolbar",
            }
        )

    cookie_terms = (
        "cookie",
        "cookies",
        "persist",
        "preferences",
    )
    toolbar_terms = (
        "toolbar",
        "recite",
    )
    if any(t in q for t in cookie_terms) and any(t in q for t in toolbar_terms):
        expanded.update(
            {
                "recite",
                "persist",
                "preferences",
                "storage",
                "localstorage",
                "cookie",
                "toolbar",
                "recitejs",
                "recite_persist",
                "recite_preferences",
            }
        )

    return sorted(expanded)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _bm25_candidates(
    conn: sqlite3.Connection,
    fts_query: str,
    limit: int,
    docs_only: bool = False,
) -> list[sqlite3.Row]:
    if docs_only:
        return conn.execute(
            """
            SELECT
              c.id,
              c.repo,
              c.rel_path,
              c.start_line,
              c.end_line,
              c.content,
              c.source_type,
              bm25(chunks_fts) AS bm25_score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
              AND c.source_type = 'doc'
            ORDER BY bm25_score
            LIMIT ?
            """,
            (fts_query, int(limit)),
        ).fetchall()

    return conn.execute(
        """
        SELECT
          c.id,
          c.repo,
          c.rel_path,
          c.start_line,
          c.end_line,
          c.content,
          c.source_type,
          bm25(chunks_fts) AS bm25_score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY bm25_score
        LIMIT ?
        """,
        (fts_query, int(limit)),
    ).fetchall()


def _embedding_candidates(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    docs_only: bool = False,
) -> list[dict]:
    if not ENABLE_EMBEDDINGS:
        return []

    query_embeddings = ollama_embed_texts([query], model=EMBED_MODEL)
    if not query_embeddings:
        return []
    query_vector = query_embeddings[0]

    if docs_only:
        rows = conn.execute(
            """
            SELECT
              c.id,
              c.repo,
              c.rel_path,
              c.start_line,
              c.end_line,
              c.content,
              c.source_type,
              e.embedding_json
            FROM chunk_embeddings e
            JOIN chunks c ON c.id = e.chunk_id
            WHERE c.source_type = 'doc'
            LIMIT ?
            """,
            (int(MAX_EMBED_SCAN),),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
              c.id,
              c.repo,
              c.rel_path,
              c.start_line,
              c.end_line,
              c.content,
              c.source_type,
              e.embedding_json
            FROM chunk_embeddings e
            JOIN chunks c ON c.id = e.chunk_id
            LIMIT ?
            """,
            (int(MAX_EMBED_SCAN),),
        ).fetchall()

    scored: list[dict] = []
    for row in rows:
        try:
            vector = json.loads(row["embedding_json"])
        except Exception:  # noqa: BLE001
            continue
        sim = _cosine_similarity(query_vector, vector)
        scored.append(
            {
                "id": row["id"],
                "repo": row["repo"],
                "rel_path": row["rel_path"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "content": row["content"],
                "source_type": row["source_type"],
                "semantic_score": sim,
            }
        )

    scored.sort(key=lambda r: r["semantic_score"], reverse=True)
    return scored[: int(limit)]


def _source_boost(source_type: str, rel_path: str, repo: str) -> float:
    if repo == "KnowledgeBase":
        return KB_SOURCE_BOOST
    if "RAG_DOC/" in rel_path or rel_path.startswith("RAG_DOC/"):
        return RAG_DOC_SOURCE_BOOST
    if source_type == "doc":
        return DOC_SOURCE_BOOST
    return CODE_SOURCE_BOOST


def _intent_boost(item: dict, query: str) -> float:
    q = query.lower()
    repo = item["repo"]
    rel = item["rel_path"]
    rel_lower = rel.lower()
    boost = 0.0

    launcher_intent_terms = (
        "launcher",
        "floating",
        "bottom right",
        "accessibility tools",
        "data-clientid",
        "script",
        "website",
    )
    if any(t in q for t in launcher_intent_terms):
        if repo == "Recite.toolbar.launcher":
            boost += 0.20
            if rel.startswith("RAG_DOC/"):
                boost += 0.10
            if "launcher-e2e-guide.md" in rel_lower:
                boost += 0.22
            if "launcher-attribute-reference.md" in rel_lower:
                boost += 0.20
            if "launcher-integration-playbooks.md" in rel_lower:
                boost += 0.14
            if "launcher-events-and-api.md" in rel_lower:
                boost += 0.04
        if "recite_implementation_instructions" in rel:
            boost += 0.08
        if "handover.md" in rel_lower:
            boost -= 0.24

    setup_intent_terms = (
        "how do i add",
        "add the toolbar",
        "to my website",
        "bottom right",
        "accessibility tools",
    )
    if any(t in q for t in setup_intent_terms):
        if repo == "Recite.toolbar.launcher":
            if "launcher-e2e-guide.md" in rel_lower:
                boost += 0.35
            if "launcher-attribute-reference.md" in rel_lower:
                boost += 0.30
            if "launcher-integration-playbooks.md" in rel_lower:
                boost += 0.22
            if "launcher-events-and-api.md" in rel_lower:
                boost -= 0.06
        if "handover.md" in rel_lower:
            boost -= 0.16
        # For "add toolbar to website" queries, legacy toolbar docs are often
        # semantically close but usually not the preferred launcher-first guidance.
        if repo == "recite-toolbar":
            boost -= 0.24
        if "recite_implementation_instructions" in rel_lower:
            boost -= 0.30
        if "recite_implementation.js" in rel_lower:
            boost -= 0.25

    tts_pronunciation_terms = (
        "tts",
        "text to speech",
        "pronunciation",
        "pronounce",
        "acronym",
        "initials",
        "read as",
    )
    if any(t in q for t in tts_pronunciation_terms):
        if repo == "recite-toolbar":
            boost += 0.16
            if "options-reference.generated.md" in rel_lower:
                boost += 0.34
            if "rag_doc/" in rel_lower:
                boost += 0.08
        if repo == "Recite.toolbar.launcher":
            boost -= 0.14
        if "dom.word_filter" in item.get("content", "").lower():
            boost += 0.28

    recent_changes_terms = (
        "recent",
        "recent changes",
        "latest",
        "what changed",
        "changelog",
        "release notes",
        "updates",
        "new in",
    )
    change_intent = any(t in q for t in recent_changes_terms)
    if "changelog" in rel_lower or "release" in rel_lower:
        if change_intent:
            boost += 0.42
            if repo == "recite-toolbar":
                boost += 0.18
        else:
            boost -= 0.08

    if "library/Aws/" in rel or "library/Aws_OLD/" in rel:
        boost -= 0.25

    cookie_terms = (
        "cookie",
        "cookies",
        "persist",
        "preferences",
    )
    toolbar_terms = (
        "toolbar",
        "recite",
    )
    cookie_intent = any(t in q for t in cookie_terms) and any(t in q for t in toolbar_terms)
    if cookie_intent:
        if repo == "recite-toolbar":
            boost += 0.28
            if rel_lower == "src/js/recite.js":
                boost += 0.34
            if rel_lower == "src/js/recite/preferences.js":
                boost += 0.34
            if rel_lower == "src/js/recite/storage/cookie.js":
                boost += 0.34
            if rel_lower.startswith("src/js/recite/"):
                boost += 0.16
        if repo == "Recite.toolbar.launcher":
            boost += 0.10
            if "reciteme_toolbar_launcher.js" in rel_lower:
                boost += 0.18
        if repo == "recite-api":
            if rel_lower.startswith("library/"):
                boost -= 0.46
            if "guzzlehttp" in rel_lower or "psr/" in rel_lower:
                boost -= 0.28

    return boost


def _rerank_score(item: dict, query: str, tokens: list[str]) -> float:
    text = f"{item['rel_path']}\n{item['content']}".lower()
    if not tokens:
        coverage = 0.0
    else:
        matched = sum(1 for t in tokens if t in text)
        coverage = matched / len(tokens)

    phrase_bonus = 0.12 if query.lower() in text else 0.0
    path_bonus = 0.08 if any(t in item["rel_path"].lower() for t in tokens) else 0.0
    return item["score"] + (0.32 * coverage) + phrase_bonus + path_bonus + (
        _source_boost(item["source_type"], item["rel_path"], item["repo"]) - 1.0
    ) + _intent_boost(item, query)


def search_chunks(query: str, k: int = 6, docs_only: bool = False) -> list[SearchHit]:
    query = (query or "").strip()
    if not query:
        return []

    tokens = _tokenize(query)
    expanded_tokens = _expand_tokens_for_intent(tokens, query)
    fts_query = _build_fts_query(expanded_tokens)
    if not fts_query:
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    candidate_limit = max(int(k) * 6, RETRIEVAL_CANDIDATES)
    bm25_rows = _bm25_candidates(conn, fts_query, candidate_limit, docs_only=docs_only)

    semantic_rows: list[dict] = []
    try:
        semantic_rows = _embedding_candidates(conn, query, candidate_limit, docs_only=docs_only)
    except Exception:
        semantic_rows = []

    conn.close()

    lexical_weight = max(0.0, min(1.0, HYBRID_ALPHA))
    semantic_weight = 1.0 - lexical_weight

    merged: dict[int, dict] = {}
    for rank, row in enumerate(bm25_rows, start=1):
        existing = merged.get(row["id"])
        score = lexical_weight / (RRF_K + rank)
        if existing is None:
            merged[row["id"]] = {
                "id": row["id"],
                "repo": row["repo"],
                "rel_path": row["rel_path"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "content": row["content"],
                "source_type": row["source_type"],
                "score": score,
            }
        else:
            existing["score"] += score

    for rank, row in enumerate(semantic_rows, start=1):
        score = semantic_weight / (RRF_K + rank)
        existing = merged.get(row["id"])
        if existing is None:
            merged[row["id"]] = {
                "id": row["id"],
                "repo": row["repo"],
                "rel_path": row["rel_path"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "content": row["content"],
                "source_type": row["source_type"],
                "score": score,
            }
        else:
            existing["score"] += score

    ranked = list(merged.values())
    feedback_biases = get_feedback_biases(
        query,
        [(str(item["repo"]), str(item["rel_path"])) for item in ranked],
    )
    for item in ranked:
        item["score"] = _rerank_score(item, query, expanded_tokens) + feedback_biases.get(
            (str(item["repo"]), str(item["rel_path"])),
            0.0,
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)

    return [
        SearchHit(
            id=int(r["id"]),
            repo=str(r["repo"]),
            rel_path=str(r["rel_path"]),
            start_line=int(r["start_line"]),
            end_line=int(r["end_line"]),
            content=str(r["content"]),
            source_type=str(r["source_type"]),
            score=float(r["score"]),
        )
        for r in ranked[: int(k)]
    ]


def serialize_hits(hits: list[SearchHit]) -> list[dict]:
    return [asdict(h) for h in hits]
