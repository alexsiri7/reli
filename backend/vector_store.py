"""ChromaDB vector store for semantic search over Things."""

import json
import logging
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb import EmbeddingFunction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CHROMA_PATH = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "things"

REQUESTY_BASE_URL = os.environ.get("REQUESTY_BASE_URL", "https://router.requesty.ai/v1")
REQUESTY_API_KEY = os.environ.get("REQUESTY_API_KEY", "")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Threshold: use vector search when Things count >= this value
VECTOR_SEARCH_THRESHOLD = 500


# ---------------------------------------------------------------------------
# Embedding function
# ---------------------------------------------------------------------------


class _ThingEmbedder(EmbeddingFunction):
    """Embed text via Requesty (OpenAI-compatible) with Ollama fallback."""

    def __call__(self, input: list[str]) -> list[list[float]]:  # type: ignore[override]  # noqa: A002
        # Try Requesty first (if API key configured)
        if REQUESTY_API_KEY:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=REQUESTY_API_KEY, base_url=REQUESTY_BASE_URL)
                resp = client.embeddings.create(model=EMBEDDING_MODEL, input=input)
                return [e.embedding for e in resp.data]
            except Exception as exc:
                logger.warning("Requesty embedding failed, falling back to Ollama: %s", exc)

        # Fallback: Ollama HTTP API
        import urllib.request

        embeddings = []
        for text in input:
            payload = json.dumps({"model": OLLAMA_EMBED_MODEL, "prompt": text}).encode()
            req = urllib.request.Request(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            embeddings.append(data["embedding"])
        return embeddings


_embedder = _ThingEmbedder()


# ---------------------------------------------------------------------------
# ChromaDB client / collection helpers
# ---------------------------------------------------------------------------


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedder,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _thing_to_text(thing: dict[str, Any]) -> str:
    """Flatten a Thing dict into a single searchable string."""
    parts: list[str] = []
    if thing.get("title"):
        parts.append(thing["title"])
    if thing.get("type_hint"):
        parts.append(f"type:{thing['type_hint']}")
    raw_data = thing.get("data")
    if raw_data:
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data) if raw_data else {}
        if isinstance(raw_data, dict):
            for k, v in raw_data.items():
                parts.append(f"{k}:{v}")
    return " | ".join(parts)


def upsert_thing(thing: dict[str, Any]) -> None:
    """Embed and upsert a Thing into ChromaDB. Silently no-ops on error."""
    try:
        collection = _get_collection()
        text = _thing_to_text(thing)
        collection.upsert(
            ids=[thing["id"]],
            documents=[text],
            metadatas=[
                {
                    "type_hint": thing.get("type_hint") or "",
                    "active": 1 if thing.get("active", True) else 0,
                }
            ],
        )
    except Exception as exc:
        logger.error("ChromaDB upsert failed for thing %s: %s", thing.get("id"), exc)


def delete_thing(thing_id: str) -> None:
    """Remove a Thing from ChromaDB. Silently no-ops on error."""
    try:
        collection = _get_collection()
        collection.delete(ids=[thing_id])
    except Exception as exc:
        logger.error("ChromaDB delete failed for thing %s: %s", thing_id, exc)


def vector_count() -> int:
    """Return the number of Things indexed in ChromaDB."""
    try:
        return _get_collection().count()
    except Exception as exc:
        logger.error("ChromaDB count failed: %s", exc)
        return 0


def vector_search(
    queries: list[str],
    n_results: int = 20,
    active_only: bool = True,
    type_hint: str | None = None,
) -> list[str]:
    """Return Thing IDs ordered by semantic relevance across all queries.

    Returns an empty list on any error so callers can fall back to SQL.
    """
    try:
        collection = _get_collection()
        total = collection.count()
        if total == 0:
            return []

        # Build ChromaDB `where` filter
        filters: list[dict] = []
        if active_only:
            filters.append({"active": {"$eq": 1}})
        if type_hint:
            filters.append({"type_hint": {"$eq": type_hint}})

        where: dict | None = None
        if len(filters) == 1:
            where = filters[0]
        elif len(filters) > 1:
            where = {"$and": filters}

        per_query = min(n_results, total)
        seen_ids: list[str] = []
        seen_set: set[str] = set()

        for query in queries[:3]:
            results = collection.query(
                query_texts=[query],
                n_results=per_query,
                where=where,
            )
            for id_ in results["ids"][0]:
                if id_ not in seen_set:
                    seen_set.add(id_)
                    seen_ids.append(id_)

        return seen_ids
    except Exception as exc:
        logger.error("ChromaDB vector_search failed: %s", exc)
        return []
