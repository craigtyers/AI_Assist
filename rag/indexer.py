from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rag.config import (
    ALLOWED_EXTENSIONS,
    CHUNK_CHARS,
    CHUNK_OVERLAP,
    DB_PATH,
    DOC_EXTENSIONS,
    EMBED_BATCH_SIZE,
    EMBED_MODEL,
    ENABLE_EMBEDDINGS,
    EXCLUDED_DIRS,
    EXCLUDED_PATH_SUBSTRINGS,
    MAX_FILE_BYTES,
    MIN_CHUNK_CHARS,
    REPO_PATHS,
)
from rag.ollama_client import ollama_embed_texts


@dataclass
class Chunk:
    repo: str
    rel_path: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    source_type: str


def should_index_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    name_lower = path.name.lower()
    is_extensionless_changelog = suffix == "" and name_lower in {"changelog", "release-notes", "releasenotes"}
    if suffix not in ALLOWED_EXTENSIONS and not is_extensionless_changelog:
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return size <= MAX_FILE_BYTES


def iter_repo_files(repo_path: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in files:
            full = Path(root) / name
            rel = full.relative_to(repo_path).as_posix()
            if any(s in rel for s in EXCLUDED_PATH_SUBSTRINGS):
                continue
            if should_index_file(full):
                yield full


def detect_source_type(repo: str, rel_path: str) -> str:
    if repo == "KnowledgeBase":
        return "doc"
    parts = Path(rel_path).parts
    if "RAG_DOC" in parts:
        return "doc"
    p = Path(rel_path)
    suffix = p.suffix.lower()
    if suffix == "" and p.name.lower() in {"changelog", "release-notes", "releasenotes"}:
        return "doc"
    return "doc" if suffix in DOC_EXTENSIONS else "code"


def _line_looks_like_boundary(line: str) -> bool:
    if not line.strip():
        return True
    boundary_patterns = (
        r"^\s*(def|class)\s+",
        r"^\s*(export\s+)?(async\s+)?function\s+",
        r"^\s*(export\s+)?(const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*(async\s*)?\(",
        r"^\s*(interface|type|enum)\s+",
        r"^\s*(public|private|protected)\s+",
        r"^\s*@",
        r"^\s*module\s+",
        r"^\s*#\s+",
        r"^\s*##\s+",
    )
    return any(re.search(pat, line) for pat in boundary_patterns)


def chunk_text(text: str, repo: str, rel_path: str) -> list[Chunk]:
    if not text.strip():
        return []

    source_type = detect_source_type(repo, rel_path)
    lines = text.splitlines()
    chunks: list[Chunk] = []
    buf: list[str] = []
    char_count = 0
    start = 1

    def flush(end_line: int) -> None:
        nonlocal buf, char_count, start
        content = "".join(buf).strip()
        if not content:
            return

        chunks.append(
            Chunk(
                repo=repo,
                rel_path=rel_path,
                start_line=start,
                end_line=end_line,
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                source_type=source_type,
            )
        )

        overlap_text = content[-CHUNK_OVERLAP:] if CHUNK_OVERLAP > 0 else ""
        buf = [overlap_text] if overlap_text else []
        char_count = len(overlap_text)
        start = end_line

    for i, line in enumerate(lines, start=1):
        line_with_nl = line + "\n"
        buf.append(line_with_nl)
        char_count += len(line_with_nl)

        long_enough = char_count >= CHUNK_CHARS
        near_target = char_count >= MIN_CHUNK_CHARS
        boundary = _line_looks_like_boundary(line)

        if long_enough or (near_target and boundary):
            flush(i)

    tail = "".join(buf).strip()
    if tail:
        chunks.append(
            Chunk(
                repo=repo,
                rel_path=rel_path,
                start_line=start,
                end_line=len(lines),
                content=tail,
                content_hash=hashlib.sha256(tail.encode("utf-8")).hexdigest(),
                source_type=source_type,
            )
        )

    return chunks


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'code'
        );

        CREATE TABLE IF NOT EXISTS chunk_embeddings (
            chunk_id INTEGER PRIMARY KEY,
            embedding_json TEXT NOT NULL,
            dims INTEGER NOT NULL,
            FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content,
            rel_path,
            repo,
            source_type,
            content='chunks',
            content_rowid='id'
        );
        """
    )

    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(chunks)").fetchall()
    }
    if "source_type" not in columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN source_type TEXT NOT NULL DEFAULT 'code'")


def rebuild_index(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM chunk_embeddings")
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM chunks_fts")


def _index_embeddings_for_rows(
    conn: sqlite3.Connection,
    rows: list[tuple[int, str]],
) -> int:
    if not rows:
        return 0

    indexed = 0
    for i in range(0, len(rows), EMBED_BATCH_SIZE):
        batch = rows[i : i + EMBED_BATCH_SIZE]
        texts = [r[1] for r in batch]
        vectors = ollama_embed_texts(texts, model=EMBED_MODEL)

        if len(vectors) != len(batch):
            raise RuntimeError(
                f"Embedding count mismatch: expected {len(batch)}, got {len(vectors)}"
            )

        conn.executemany(
            """
            INSERT OR REPLACE INTO chunk_embeddings (chunk_id, embedding_json, dims)
            VALUES (?, ?, ?)
            """,
            [
                (chunk_id, json.dumps(vector), len(vector))
                for (chunk_id, _text), vector in zip(batch, vectors)
            ],
        )
        indexed += len(batch)
    return indexed


def index_all_repos() -> dict[str, int | str | bool]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    rebuild_index(conn)

    repo_count = 0
    file_count = 0
    chunk_count = 0
    embedding_count = 0
    embed_enabled = ENABLE_EMBEDDINGS
    embed_error = ""

    for repo_path in REPO_PATHS:
        repo_path = repo_path.resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            print(f"[warn] repo path not found, skipping: {repo_path}")
            continue

        repo_count += 1
        repo_name = repo_path.name

        for file_path in iter_repo_files(repo_path):
            file_count += 1
            rel_path = str(file_path.relative_to(repo_path))

            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            except OSError:
                continue

            chunks = chunk_text(text, repo_name, rel_path)
            if not chunks:
                continue

            before_max_id = conn.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM chunks").fetchone()[
                "max_id"
            ]

            conn.executemany(
                """
                INSERT INTO chunks (repo, rel_path, start_line, end_line, content, content_hash, source_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.repo,
                        c.rel_path,
                        c.start_line,
                        c.end_line,
                        c.content,
                        c.content_hash,
                        c.source_type,
                    )
                    for c in chunks
                ],
            )
            chunk_count += len(chunks)

            if embed_enabled:
                new_rows = [
                    (before_max_id + idx + 1, c.content)
                    for idx, c in enumerate(chunks)
                ]
                try:
                    embedding_count += _index_embeddings_for_rows(conn, new_rows)
                except Exception as exc:  # noqa: BLE001
                    embed_enabled = False
                    embed_error = str(exc)
                    print(f"[warn] disabling embeddings for this indexing run: {exc}")

    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()

    return {
        "repos": repo_count,
        "files": file_count,
        "chunks": chunk_count,
        "embeddings_enabled": bool(embed_enabled),
        "embedded_chunks": embedding_count,
        "embedding_error": embed_error,
        "db_path": str(DB_PATH),
    }


if __name__ == "__main__":
    summary = index_all_repos()
    print(
        f"Indexed {summary['repos']} repo(s), {summary['files']} file(s), {summary['chunks']} chunk(s), "
        f"{summary['embedded_chunks']} embedded chunk(s) -> {summary['db_path']}"
    )
