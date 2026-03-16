"""ChromaDB vector store for semantic search over Things."""

import json
import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb import EmbeddingFunction

from .settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CHROMA_PATH = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "things"

REQUESTY_BASE_URL = settings.requesty_base_url
REQUESTY_API_KEY = settings.requesty_api_key
EMBEDDING_MODEL = settings.embedding_model

OLLAMA_BASE_URL = settings.ollama_base_url
OLLAMA_EMBED_MODEL = settings.ollama_embed_model

# Threshold: use vector search when Things count >= this value
VECTOR_SEARCH_THRESHOLD = 0


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
    """Flatten a Thing dict into a rich searchable string.

    Includes title (repeated for weight), type, formatted data fields,
    and titles of related Things for relationship context.
    """
    from .database import db

    parts: list[str] = []
    title = thing.get("title") or ""
    if title:
        # Repeat title for extra weight in embedding
        parts.append(title)
        parts.append(title)
    if thing.get("type_hint"):
        parts.append(f"type: {thing['type_hint']}")

    # Format data fields with human-readable labels
    raw_data = thing.get("data")
    if raw_data:
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except (json.JSONDecodeError, ValueError):
                raw_data = None
        if isinstance(raw_data, dict):
            for k, v in raw_data.items():
                label = k.replace("_", " ").replace("-", " ")
                if isinstance(v, list):
                    v = ", ".join(str(item) for item in v)
                elif isinstance(v, dict):
                    v = json.dumps(v)
                parts.append(f"{label}: {v}")

    # Relationship context: fetch related Things' titles
    thing_id = thing.get("id")
    if thing_id:
        try:
            with db() as conn:
                rows = conn.execute(
                    "SELECT t.title, r.relationship_type"
                    " FROM thing_relationships r"
                    " JOIN things t ON t.id = CASE"
                    "   WHEN r.from_thing_id = ? THEN r.to_thing_id"
                    "   ELSE r.from_thing_id END"
                    " WHERE r.from_thing_id = ? OR r.to_thing_id = ?",
                    (thing_id, thing_id, thing_id),
                ).fetchall()
                if rows:
                    related = [f"{row['title']} ({row['relationship_type']})" for row in rows]
                    parts.append("related to: " + ", ".join(related))
        except Exception as exc:
            logger.debug("Could not fetch relationships for thing %s: %s", thing_id, exc)

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
                    "user_id": thing.get("user_id") or "",
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


def reindex_all() -> int:
    """Delete and re-embed all Things from the database.

    Returns the number of Things re-indexed.
    """
    from .database import db

    try:
        collection = _get_collection()
        # Clear existing embeddings
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])

        # Fetch all things from the database
        with db() as conn:
            rows = conn.execute("SELECT * FROM things").fetchall()

        if not rows:
            return 0

        # Batch upsert
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str | int]] = []
        for row in rows:
            thing = dict(row)
            ids.append(thing["id"])
            documents.append(_thing_to_text(thing))
            metadatas.append(
                {
                    "type_hint": thing.get("type_hint") or "",
                    "active": 1 if thing.get("active", True) else 0,
                    "user_id": thing.get("user_id") or "",
                }
            )

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)  # type: ignore[arg-type]
        return len(ids)
    except Exception as exc:
        logger.error("ChromaDB reindex_all failed: %s", exc)
        raise


def vector_search(
    queries: list[str],
    n_results: int = 20,
    active_only: bool = True,
    type_hint: str | None = None,
    user_id: str = "",
) -> list[str]:
    """Return Thing IDs ordered by semantic relevance across all queries.

    When user_id is provided, only returns Things belonging to that user
    (or Things with no user_id for backward compatibility).
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
        if user_id:
            filters.append({"$or": [{"user_id": {"$eq": user_id}}, {"user_id": {"$eq": ""}}]})

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
