"""Supabase database implementation — PostgREST-backed alternative to SQLite.

Provides the same entry points as database.py (get_connection, db, init_db,
clean_orphan_relationships) but backed by Supabase. Activated when
STORAGE_BACKEND=supabase.

The Supabase client uses the PostgREST API, so callers receive a
supabase.Client instead of sqlite3.Connection. Router-level code must
handle both types (gated by STORAGE_BACKEND).
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast

from supabase import Client, create_client  # type: ignore[attr-defined]

from .config import settings

logger = logging.getLogger(__name__)

_client: Client | None = None

# Tables expected by the application (must match the Supabase migration).
_EXPECTED_TABLES = [
    "users",
    "things",
    "thing_types",
    "thing_relationships",
    "chat_history",
    "chat_message_usage",
    "conversation_summaries",
    "sweep_findings",
    "usage_log",
    "connection_suggestions",
    "google_tokens",
    "user_settings",
    "merge_history",
    "sweep_runs",
    "morning_briefings",
]


def get_client() -> Client:
    """Return a module-level singleton Supabase client."""
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _client


@contextmanager
def supabase_db() -> Generator[Client, None, None]:
    """Context manager yielding a Supabase client.

    Unlike the SQLite ``db()`` context manager there is no local transaction
    to commit or rollback — each PostgREST call is its own transaction on
    the Supabase side.
    """
    yield get_client()


def init_db_supabase() -> None:
    """Verify Supabase connectivity and that expected tables are accessible.

    Schema creation is handled by Supabase migrations (see
    ``supabase/migrations/``), not by application code.  This function
    performs a lightweight probe on each table to confirm it exists and is
    reachable with the configured credentials.
    """
    client = get_client()
    for table in _EXPECTED_TABLES:
        # Select zero rows — just enough to confirm the table is accessible.
        client.table(table).select("*", count="exact").limit(0).execute()  # type: ignore[arg-type]
    logger.info("Supabase: all %d expected tables verified", len(_EXPECTED_TABLES))


def clean_orphan_relationships_supabase() -> tuple[int, list[str]]:
    """Delete relationships where from_thing_id or to_thing_id no longer exists.

    Returns ``(deleted_count, list_of_deleted_ids)``.
    """
    client = get_client()

    # Fetch all existing thing IDs.
    things_resp = client.table("things").select("id").execute()
    things_data: list[dict[str, Any]] = cast(list[dict[str, Any]], things_resp.data)
    thing_ids = {row["id"] for row in things_data}

    # Fetch all relationships (id + FK columns only).
    rels_resp = client.table("thing_relationships").select("id,from_thing_id,to_thing_id").execute()
    rels_data: list[dict[str, Any]] = cast(list[dict[str, Any]], rels_resp.data)

    orphan_ids: list[str] = [
        row["id"] for row in rels_data if row["from_thing_id"] not in thing_ids or row["to_thing_id"] not in thing_ids
    ]

    if orphan_ids:
        for oid in orphan_ids:
            client.table("thing_relationships").delete().eq("id", oid).execute()
        logger.info("Cleaned %d orphan relationship(s): %s", len(orphan_ids), orphan_ids)

    return len(orphan_ids), orphan_ids


# ---------------------------------------------------------------------------
# Conversation summary helpers
# ---------------------------------------------------------------------------


def get_latest_summary_supabase(user_id: str) -> dict[str, Any] | None:
    """Get the most recent conversation summary for a user via Supabase."""
    client = get_client()
    resp = (
        client.table("conversation_summaries")
        .select("*")
        .eq("user_id", user_id)
        .order("messages_summarized_up_to", desc=True)
        .limit(1)
        .execute()
    )
    data: list[dict[str, Any]] = cast(list[dict[str, Any]], resp.data)
    return data[0] if data else None


def create_summary_supabase(
    user_id: str,
    summary_text: str,
    messages_summarized_up_to: int,
    token_count: int = 0,
) -> int:
    """Insert a conversation summary and return its id."""
    client = get_client()
    resp = (
        client.table("conversation_summaries")
        .insert(
            {
                "user_id": user_id,
                "summary_text": summary_text,
                "messages_summarized_up_to": messages_summarized_up_to,
                "token_count": token_count,
            }
        )
        .execute()
    )
    inserted: list[dict[str, Any]] = cast(list[dict[str, Any]], resp.data)
    if not inserted:
        raise RuntimeError("INSERT into conversation_summaries failed to return data")
    row_id = inserted[0].get("id")
    if row_id is None:
        raise RuntimeError("INSERT into conversation_summaries returned no id")
    return int(row_id)


def get_messages_since_summary_supabase(user_id: str) -> list[dict[str, Any]]:
    """Return chat messages since the last summary for a user."""
    latest = get_latest_summary_supabase(user_id)
    client = get_client()

    query = (
        client.table("chat_history")
        .select("id,session_id,role,content,timestamp")
        .eq("user_id", user_id)
        .order("id", desc=False)
    )
    if latest:
        query = query.gt("id", latest["messages_summarized_up_to"])

    resp = query.execute()
    return cast(list[dict[str, Any]], resp.data)


def get_message_count_since_summary_supabase(user_id: str) -> int:
    """Count chat messages since the last summary for a user."""
    latest = get_latest_summary_supabase(user_id)
    client = get_client()

    query = (
        client.table("chat_history")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .limit(0)
    )
    if latest:
        query = query.gt("id", latest["messages_summarized_up_to"])

    resp = query.execute()
    return resp.count or 0
