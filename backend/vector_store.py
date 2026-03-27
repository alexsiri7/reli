"""Vector store for semantic search over Things.

Supports two backends controlled by ``settings.STORAGE_BACKEND``:

* ``sqlite`` (default) — ChromaDB persistent client (local disk)
* ``supabase`` — pgvector via Supabase PostgREST + RPC functions
"""

import json
import logging
from pathlib import Path
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CHROMA_PATH = Path(settings.DATA_DIR) / "chroma_db"
COLLECTION_NAME = "things"

REQUESTY_BASE_URL = settings.REQUESTY_BASE_URL
REQUESTY_API_KEY = settings.REQUESTY_API_KEY
EMBEDDING_MODEL = settings.EMBEDDING_MODEL

OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
OLLAMA_EMBED_MODEL = settings.OLLAMA_EMBED_MODEL

# Threshold: use vector search when Things count >= this value
VECTOR_SEARCH_THRESHOLD = 0


# ---------------------------------------------------------------------------
# Embedding function (shared by both backends)
# ---------------------------------------------------------------------------


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via Requesty (OpenAI-compatible) with Ollama fallback."""
    # Try Requesty first (if API key configured)
    if REQUESTY_API_KEY:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=REQUESTY_API_KEY, base_url=REQUESTY_BASE_URL)
            resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [e.embedding for e in resp.data]
        except Exception as exc:
            logger.warning("Requesty embedding failed, falling back to Ollama: %s", exc)

    # Fallback: Ollama HTTP API
    import urllib.request

    embeddings = []
    for text in texts:
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


# ---------------------------------------------------------------------------
# ChromaDB embedding adapter (wraps _embed_texts for ChromaDB interface)
# ---------------------------------------------------------------------------

_USE_SUPABASE = settings.STORAGE_BACKEND == "supabase"

if not _USE_SUPABASE:
    import sys
    import types

    # ---------------------------------------------------------------------------
    # Suppress ChromaDB PostHog telemetry (re-s5ne)
    # ---------------------------------------------------------------------------
    if "posthog" not in sys.modules:
        _posthog_stub = types.ModuleType("posthog")
        _posthog_stub.capture = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
        _posthog_stub.disabled = True  # type: ignore[attr-defined]
        _posthog_stub.project_api_key = ""  # type: ignore[attr-defined]
        sys.modules["posthog"] = _posthog_stub

    import chromadb
    from chromadb import EmbeddingFunction

    class _ThingEmbedder(EmbeddingFunction):
        """ChromaDB embedding function adapter."""

        def __call__(self, input: list[str]) -> list[list[float]]:  # type: ignore[override]  # noqa: A002
            return _embed_texts(input)

    _embedder = _ThingEmbedder()


# ---------------------------------------------------------------------------
# ChromaDB client / collection helpers
# ---------------------------------------------------------------------------


def _get_collection() -> "chromadb.Collection":
    client = chromadb.PersistentClient(
        path=str(CHROMA_PATH),
        settings=chromadb.Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedder,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _thing_to_text(thing: dict[str, Any]) -> str:
    """Flatten a Thing dict into a rich searchable string.

    Includes title (repeated for weight), type, formatted data fields,
    and titles of related Things for relationship context.
    """
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
            related = _fetch_related_titles(thing_id)
            if related:
                parts.append("related to: " + ", ".join(related))
        except Exception as exc:
            logger.debug("Could not fetch relationships for thing %s: %s", thing_id, exc)

    return " | ".join(parts)


def _fetch_related_titles(thing_id: str) -> list[str]:
    """Fetch titles of related Things, handling both backends."""
    if _USE_SUPABASE:
        return _fetch_related_titles_supabase(thing_id)
    return _fetch_related_titles_sqlite(thing_id)


def _fetch_related_titles_sqlite(thing_id: str) -> list[str]:
    from .database import db

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
        return [f"{row['title']} ({row['relationship_type']})" for row in rows]


def _fetch_related_titles_supabase(thing_id: str) -> list[str]:
    from .database_supabase import get_client

    client = get_client()

    # Fetch relationships where this thing is involved (both directions)
    from_resp = (
        client.table("thing_relationships")
        .select("to_thing_id, relationship_type")
        .eq("from_thing_id", thing_id)
        .execute()
    )
    to_resp = (
        client.table("thing_relationships")
        .select("from_thing_id, relationship_type")
        .eq("to_thing_id", thing_id)
        .execute()
    )

    # Collect related IDs
    from_rows: list[dict[str, Any]] = from_resp.data  # type: ignore[assignment]
    to_rows: list[dict[str, Any]] = to_resp.data  # type: ignore[assignment]

    related_ids: list[str] = []
    for r in from_rows:
        related_ids.append(r["to_thing_id"])
    for r in to_rows:
        related_ids.append(r["from_thing_id"])

    if not related_ids:
        return []

    # Fetch titles
    things_resp = client.table("things").select("id, title").in_("id", related_ids).execute()
    things_data: list[dict[str, Any]] = things_resp.data  # type: ignore[assignment]
    title_map = {t["id"]: t["title"] for t in things_data}

    result = []
    for r in from_rows:
        title = title_map.get(r["to_thing_id"], "")
        if title:
            result.append(f"{title} ({r['relationship_type']})")
    for r in to_rows:
        title = title_map.get(r["from_thing_id"], "")
        if title:
            result.append(f"{title} ({r['relationship_type']})")
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def upsert_thing(thing: dict[str, Any]) -> None:
    """Embed and upsert a Thing into the vector store. Silently no-ops on error."""
    if _USE_SUPABASE:
        return _upsert_thing_supabase(thing)
    return _upsert_thing_chroma(thing)


def delete_thing(thing_id: str) -> None:
    """Remove a Thing from the vector store. Silently no-ops on error."""
    if _USE_SUPABASE:
        return _delete_thing_supabase(thing_id)
    return _delete_thing_chroma(thing_id)


def vector_count() -> int:
    """Return the number of Things indexed in the vector store."""
    if _USE_SUPABASE:
        return _vector_count_supabase()
    return _vector_count_chroma()


def reindex_all() -> int:
    """Delete and re-embed all Things from the database.

    Returns the number of Things re-indexed.
    """
    if _USE_SUPABASE:
        return _reindex_all_supabase()
    return _reindex_all_chroma()


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
    if _USE_SUPABASE:
        return _vector_search_supabase(queries, n_results, active_only, type_hint, user_id)
    return _vector_search_chroma(queries, n_results, active_only, type_hint, user_id)


# ---------------------------------------------------------------------------
# ChromaDB implementations
# ---------------------------------------------------------------------------


def _upsert_thing_chroma(thing: dict[str, Any]) -> None:
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


def _delete_thing_chroma(thing_id: str) -> None:
    try:
        collection = _get_collection()
        collection.delete(ids=[thing_id])
    except Exception as exc:
        logger.error("ChromaDB delete failed for thing %s: %s", thing_id, exc)


def _vector_count_chroma() -> int:
    try:
        return _get_collection().count()
    except Exception as exc:
        logger.error("ChromaDB count failed: %s", exc)
        return 0


def _reindex_all_chroma() -> int:
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


def _vector_search_chroma(
    queries: list[str],
    n_results: int,
    active_only: bool,
    type_hint: str | None,
    user_id: str,
) -> list[str]:
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


# ---------------------------------------------------------------------------
# Supabase / pgvector implementations
# ---------------------------------------------------------------------------


def _get_supabase_client() -> Any:
    from .database_supabase import get_client

    return get_client()


def _upsert_thing_supabase(thing: dict[str, Any]) -> None:
    try:
        text = _thing_to_text(thing)
        embeddings = _embed_texts([text])
        embedding = embeddings[0]

        client = _get_supabase_client()
        client.table("things").update({"embedding": embedding}).eq("id", thing["id"]).execute()
    except Exception as exc:
        logger.error("pgvector upsert failed for thing %s: %s", thing.get("id"), exc)


def _delete_thing_supabase(thing_id: str) -> None:
    """Clear embedding for a deleted thing.

    The thing row itself is deleted by the caller; if it's already gone,
    the update is a no-op. This is just belt-and-suspenders cleanup.
    """
    try:
        client = _get_supabase_client()
        client.table("things").update({"embedding": None}).eq("id", thing_id).execute()
    except Exception as exc:
        logger.error("pgvector delete failed for thing %s: %s", thing_id, exc)


def _vector_count_supabase() -> int:
    try:
        client = _get_supabase_client()
        resp = (
            client.table("things")
            .select("id", count="exact")  # type: ignore[arg-type]
            .not_.is_("embedding", "null")
            .execute()
        )
        return resp.count or 0
    except Exception as exc:
        logger.error("pgvector count failed: %s", exc)
        return 0


def _reindex_all_supabase() -> int:
    from .database_supabase import get_client

    try:
        client = get_client()

        # Clear all existing embeddings
        client.table("things").update({"embedding": None}).not_.is_("embedding", "null").execute()

        # Fetch all things
        resp = client.table("things").select("*").execute()
        rows: list[dict[str, Any]] = resp.data  # type: ignore[assignment]
        if not rows:
            return 0

        # Batch embed (process in chunks to avoid API limits)
        batch_size = 50
        total_indexed = 0

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            texts = [_thing_to_text(thing) for thing in batch]
            embeddings = _embed_texts(texts)

            for thing, embedding in zip(batch, embeddings):
                client.table("things").update({"embedding": embedding}).eq("id", thing["id"]).execute()
                total_indexed += 1

        return total_indexed
    except Exception as exc:
        logger.error("pgvector reindex_all failed: %s", exc)
        raise


def _vector_search_supabase(
    queries: list[str],
    n_results: int,
    active_only: bool,
    type_hint: str | None,
    user_id: str,
) -> list[str]:
    try:
        client = _get_supabase_client()

        # Check if there are any embeddings
        count_resp = (
            client.table("things")
            .select("id", count="exact")  # type: ignore[arg-type]
            .not_.is_("embedding", "null")
            .execute()
        )
        if not count_resp.count:
            return []

        seen_ids: list[str] = []
        seen_set: set[str] = set()

        for query in queries[:3]:
            # Generate embedding for the query text
            embeddings = _embed_texts([query])
            query_embedding = embeddings[0]

            # Call the match_things RPC function
            resp = client.rpc(
                "match_things",
                {
                    "query_embedding": query_embedding,
                    "match_count": n_results,
                    "filter_active": active_only,
                    "filter_type_hint": type_hint,
                    "filter_user_id": user_id or None,
                },
            ).execute()

            rpc_rows: list[dict[str, Any]] = resp.data  # type: ignore[assignment]
            for row in rpc_rows:
                id_ = row["id"]
                if id_ not in seen_set:
                    seen_set.add(id_)
                    seen_ids.append(id_)

        return seen_ids
    except Exception as exc:
        logger.error("pgvector vector_search failed: %s", exc)
        return []
