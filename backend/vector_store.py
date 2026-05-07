"""pgvector-backed vector store for semantic search over Things.

Stores embeddings in a ``thing_embeddings`` Postgres table using the pgvector
extension. Uses cosine distance (``<=>``) for similarity search.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy import text as sa_text
from sqlmodel import Session, select

import backend.db_engine as _engine_mod

from .config import settings
from .db_models import ThingEmbeddingRecord, ThingRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REQUESTY_BASE_URL = settings.REQUESTY_BASE_URL
REQUESTY_API_KEY = settings.REQUESTY_API_KEY
EMBEDDING_MODEL = settings.EMBEDDING_MODEL

OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
OLLAMA_EMBED_MODEL = settings.OLLAMA_EMBED_MODEL

# Threshold: use vector search when Things count >= this value
VECTOR_SEARCH_THRESHOLD = 0


# ---------------------------------------------------------------------------
# Embedding function
# ---------------------------------------------------------------------------


class _ThingEmbedder:
    """Embed text via Requesty (OpenAI-compatible) with Ollama fallback."""

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
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
# Public API
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
            with Session(_engine_mod.engine) as session:
                rows = session.execute(
                    sa_text(
                        "SELECT t.title, r.relationship_type"
                        " FROM thing_relationships r"
                        " JOIN things t ON t.id = CASE"
                        "   WHEN r.from_thing_id = :tid THEN r.to_thing_id"
                        "   ELSE r.from_thing_id END"
                        " WHERE r.from_thing_id = :tid OR r.to_thing_id = :tid"
                    ),
                    {"tid": thing_id},
                ).fetchall()
                if rows:
                    related = [f"{row.title} ({row.relationship_type})" for row in rows]
                    parts.append("related to: " + ", ".join(related))
        except Exception as exc:
            logger.debug("Could not fetch relationships for thing %s: %s", thing_id, exc)

    return " | ".join(parts)


def upsert_thing(thing: dict[str, Any]) -> None:
    """Embed and upsert a Thing into pgvector. Silently no-ops on error."""
    try:
        text = _thing_to_text(thing)
        embeddings = _embedder([text])
        embedding = embeddings[0]

        with Session(_engine_mod.engine) as session:
            # Use raw SQL for INSERT ON CONFLICT (upsert)
            session.execute(
                sa_text(
                    "INSERT INTO thing_embeddings (thing_id, embedding, content, updated_at) "
                    "VALUES (:thing_id, :embedding, :content, :updated_at) "
                    "ON CONFLICT (thing_id) DO UPDATE SET "
                    "embedding = EXCLUDED.embedding, "
                    "content = EXCLUDED.content, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "thing_id": thing["id"],
                    "embedding": str(embedding),
                    "content": text,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            session.commit()
    except Exception as exc:
        logger.error("pgvector upsert failed for thing %s: %s", thing.get("id"), exc)


def delete_thing(thing_id: str) -> None:
    """Remove a Thing's embedding from pgvector. Silently no-ops on error."""
    try:
        with Session(_engine_mod.engine) as session:
            record = session.get(ThingEmbeddingRecord, thing_id)
            if record:
                session.delete(record)
                session.commit()
    except Exception as exc:
        logger.error("pgvector delete failed for thing %s: %s", thing_id, exc)


def vector_count() -> int:
    """Return the number of Things indexed in pgvector."""
    try:
        with Session(_engine_mod.engine) as session:
            from sqlalchemy import func

            count = session.exec(select(func.count()).select_from(ThingEmbeddingRecord)).one()
            return count
    except Exception as exc:
        logger.error("pgvector count failed: %s", exc)
        return 0


def reindex_all(user_id: str = "") -> int:
    """Delete and re-embed Things for the given user (or all Things when user_id is empty).

    Returns the number of Things re-indexed.
    """
    from .db_engine import user_filter_clause

    try:
        with Session(_engine_mod.engine) as session:
            if user_id:
                # Delete only this user's embeddings (including NULL-owner Things)
                session.execute(
                    sa_text(
                        "DELETE FROM thing_embeddings WHERE thing_id IN "
                        "(SELECT id FROM things WHERE user_id = :uid OR user_id IS NULL)"
                    ),
                    {"uid": user_id},
                )
            else:
                session.execute(sa_text("DELETE FROM thing_embeddings"))
            session.commit()

        # Fetch Things scoped to this user
        with Session(_engine_mod.engine) as session:
            records = session.exec(
                select(ThingRecord).where(user_filter_clause(ThingRecord.user_id, user_id))
            ).all()

        if not records:
            return 0

        # Batch embed
        texts: list[str] = []
        thing_ids: list[str] = []
        for record in records:
            thing = record.model_dump()
            thing_ids.append(thing["id"])
            texts.append(_thing_to_text(thing))

        embeddings = _embedder(texts)

        # Batch insert
        now = datetime.now(timezone.utc)
        with Session(_engine_mod.engine) as session:
            for tid, embedding, text in zip(thing_ids, embeddings, texts):
                session.execute(
                    sa_text(
                        "INSERT INTO thing_embeddings (thing_id, embedding, content, updated_at) "
                        "VALUES (:thing_id, :embedding, :content, :updated_at) "
                        "ON CONFLICT (thing_id) DO UPDATE SET "
                        "embedding = EXCLUDED.embedding, "
                        "content = EXCLUDED.content, "
                        "updated_at = EXCLUDED.updated_at"
                    ),
                    {
                        "thing_id": tid,
                        "embedding": str(embedding),
                        "content": text,
                        "updated_at": now,
                    },
                )
            session.commit()
        return len(thing_ids)
    except Exception as exc:
        logger.error("pgvector reindex_all failed: %s", exc)
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
        with Session(_engine_mod.engine) as session:
            total = session.exec(select(func.count()).select_from(ThingEmbeddingRecord)).one()
            if total == 0:
                return []

        # Embed all queries (limit to 3)
        query_texts = queries[:3]
        query_embeddings = _embedder(query_texts)

        seen_ids: list[str] = []
        seen_set: set[str] = set()

        for query_embedding in query_embeddings:
            # Build dynamic SQL with filters
            where_clauses = []
            params: dict[str, Any] = {
                "embedding": str(query_embedding),
                "limit": n_results,
            }

            if active_only:
                where_clauses.append("t.active = true")
            if type_hint:
                where_clauses.append("t.type_hint = :type_hint")
                params["type_hint"] = type_hint
            if user_id:
                where_clauses.append("(t.user_id = :user_id OR t.user_id IS NULL)")
                params["user_id"] = user_id

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            sql = sa_text(
                f"SELECT e.thing_id "
                f"FROM thing_embeddings e "
                f"JOIN things t ON t.id = e.thing_id "
                f"{where_sql} "
                f"ORDER BY e.embedding <=> :embedding "
                f"LIMIT :limit"
            )

            with Session(_engine_mod.engine) as session:
                rows = session.execute(sql, params).fetchall()
                for row in rows:
                    tid = row[0]
                    if tid not in seen_set:
                        seen_set.add(tid)
                        seen_ids.append(tid)

        return seen_ids
    except Exception as exc:
        logger.error("pgvector vector_search failed: %s", exc)
        return []


def vector_search_with_distances(
    query: str,
    n_results: int = 20,
    active_only: bool = True,
    user_id: str = "",
) -> list[tuple[str, float]]:
    """Return (thing_id, cosine_distance) pairs ordered by similarity.

    Used by connection_sweep for distance-threshold filtering.
    """
    try:
        query_embedding = _embedder([query])[0]

        where_clauses = []
        params: dict[str, Any] = {
            "embedding": str(query_embedding),
            "limit": n_results,
        }

        if active_only:
            where_clauses.append("t.active = true")
        if user_id:
            where_clauses.append("(t.user_id = :user_id OR t.user_id IS NULL)")
            params["user_id"] = user_id

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = sa_text(
            f"SELECT e.thing_id, e.embedding <=> :embedding AS distance "
            f"FROM thing_embeddings e "
            f"JOIN things t ON t.id = e.thing_id "
            f"{where_sql} "
            f"ORDER BY distance "
            f"LIMIT :limit"
        )

        with Session(_engine_mod.engine) as session:
            rows = session.execute(sql, params).fetchall()
            return [(row[0], float(row[1])) for row in rows]
    except Exception as exc:
        logger.error("pgvector vector_search_with_distances failed: %s", exc)
        return []
