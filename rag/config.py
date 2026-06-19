from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "rag.db"
KB_DIR = ROOT / "KnowledgeBase"
KB_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_REPOS = [
    Path("/Users/craigtyers/Projects/AI/toolbar_backend_api/recite-api"),
    Path("/Users/craigtyers/Projects/AI/toolbar_frontend/recite-toolbar"),
    Path("/Users/craigtyers/Projects/AI/toolbar_launcher/Recite.toolbar.launcher"),
]

_configured_repo_paths = [
    Path(p.strip())
    for p in os.getenv("RAG_REPO_PATHS", "").split(":")
    if p.strip()
]
REPO_PATHS = _configured_repo_paths or DEFAULT_REPOS
if KB_DIR not in REPO_PATHS:
    REPO_PATHS.append(KB_DIR)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("RAG_MODEL", "qwen3:8b")
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
OLLAMA_GENERATE_TIMEOUT_SEC = int(os.getenv("RAG_OLLAMA_TIMEOUT_SEC", "240"))

MAX_FILE_BYTES = int(os.getenv("RAG_MAX_FILE_BYTES", "250000"))
CHUNK_CHARS = int(os.getenv("RAG_CHUNK_CHARS", "1400"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "200"))
MIN_CHUNK_CHARS = int(os.getenv("RAG_MIN_CHUNK_CHARS", "450"))

ENABLE_EMBEDDINGS = os.getenv("RAG_ENABLE_EMBEDDINGS", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EMBED_BATCH_SIZE = int(os.getenv("RAG_EMBED_BATCH_SIZE", "24"))
MAX_EMBED_SCAN = int(os.getenv("RAG_MAX_EMBED_SCAN", "20000"))

# Reciprocal rank fusion weighting for lexical + semantic retrieval.
HYBRID_ALPHA = float(os.getenv("RAG_HYBRID_ALPHA", "0.65"))
RRF_K = int(os.getenv("RAG_RRF_K", "60"))
RETRIEVAL_CANDIDATES = int(os.getenv("RAG_RETRIEVAL_CANDIDATES", "40"))

DOC_SOURCE_BOOST = float(os.getenv("RAG_DOC_SOURCE_BOOST", "1.12"))
RAG_DOC_SOURCE_BOOST = float(os.getenv("RAG_RAGDOC_SOURCE_BOOST", "1.35"))
KB_SOURCE_BOOST = float(os.getenv("RAG_KB_SOURCE_BOOST", "1.45"))
CODE_SOURCE_BOOST = float(os.getenv("RAG_CODE_SOURCE_BOOST", "1.0"))
MIN_EVIDENCE_HITS = int(os.getenv("RAG_MIN_EVIDENCE_HITS", "2"))
RETRY_K = int(os.getenv("RAG_RETRY_K", "8"))
MAX_PROMPT_CONTEXT_CHUNKS = int(os.getenv("RAG_MAX_PROMPT_CONTEXT_CHUNKS", "8"))
MAX_PROMPT_CHARS_PER_CHUNK = int(os.getenv("RAG_MAX_PROMPT_CHARS_PER_CHUNK", "1800"))

ALLOWED_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt", ".php", ".py", ".java", ".go", ".rb", ".yml", ".yaml", ".xml", ".html", ".css", ".scss", ".sql", ".sh", ".env", ".conf", ".ini",
}

DOC_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",
    ".adoc",
}

EXCLUDED_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "coverage", "tmp", "cache", ".next", ".nuxt", "Aws_OLD", "KB_pending",
}

EXCLUDED_PATH_SUBSTRINGS = [
    s.strip()
    for s in os.getenv(
        "RAG_EXCLUDED_PATH_SUBSTRINGS",
        "library/Aws/:library/Aws_OLD/:/vendor/",
    ).split(":")
    if s.strip()
]
