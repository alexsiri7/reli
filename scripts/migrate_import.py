#!/usr/bin/env python3
"""Import migration JSON files into Supabase with ID preservation.

Usage:
    python scripts/migrate_import.py [--dir DIR] [--supabase-url URL] [--supabase-key KEY]
    python scripts/migrate_import.py --dry-run  # Preview without writing

Reads the JSON files produced by migrate_export.py and upserts them into
Supabase via the PostgREST API. Handles:
  - Correct insert order (respecting foreign keys)
  - Column name mapping (SQLite → Supabase differences)
  - ID preservation (same primary keys)
  - Vector embedding import into things.embedding column
  - Batch upserts (1000 rows at a time to avoid payload limits)

Requires SUPABASE_URL and SUPABASE_KEY environment variables (or --flags).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Column mapping: SQLite name → Supabase name
# Tables where column names differ between backends.
# ---------------------------------------------------------------------------
COLUMN_MAP: dict[str, dict[str, str]] = {
    "conversation_summaries": {
        "summary_text": "summary",
        "messages_summarized_up_to": "message_count",
        # token_count has no Supabase equivalent — dropped during import
    },
}

# Columns to drop per table (exist in SQLite but not in Supabase schema)
DROP_COLUMNS: dict[str, set[str]] = {
    "conversation_summaries": {"token_count"},
}

# Columns to add with defaults when missing from export
ADD_COLUMNS: dict[str, dict[str, object]] = {
    "conversation_summaries": {
        "session_id": "migrated",  # Required NOT NULL in Supabase
    },
}

# Tables with auto-generated IDs in Supabase (bigint generated always as identity).
# For these tables we must NOT send the SQLite integer id — Supabase generates it.
# Instead we track the old→new ID mapping for FK fixups.
IDENTITY_TABLES = {"chat_history", "chat_message_usage", "usage_log", "google_tokens", "user_settings"}

# Import order: parents before children (foreign key dependencies).
IMPORT_ORDER = [
    "users",
    "thing_types",
    "things",
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

BATCH_SIZE = 1000


def _transform_row(table: str, row: dict, id_maps: dict[str, dict]) -> dict | None:
    """Transform a single SQLite row for Supabase insertion.

    Returns None if the row should be skipped.
    """
    # Drop columns not in Supabase schema
    for col in DROP_COLUMNS.get(table, set()):
        row.pop(col, None)

    # Rename columns
    for old_name, new_name in COLUMN_MAP.get(table, {}).items():
        if old_name in row:
            row[new_name] = row.pop(old_name)

    # Add default columns
    for col, default in ADD_COLUMNS.get(table, {}).items():
        if col not in row:
            row[col] = default

    # Handle identity tables: strip the old integer id (Supabase auto-generates)
    if table in IDENTITY_TABLES:
        row.pop("id", None)

    # Fix up FK references that point to identity-table IDs
    if table == "chat_message_usage" and "chat_message_id" in row:
        old_fk = row["chat_message_id"]
        chat_map = id_maps.get("chat_history", {})
        if old_fk in chat_map:
            row["chat_message_id"] = chat_map[old_fk]
        else:
            # FK target not found — skip row to avoid constraint violation
            return None

    # Convert SQLite booleans (0/1) to proper booleans for jsonb columns
    # PostgREST handles this for boolean columns, but be explicit
    if table == "things":
        for bool_col in ("active", "surface"):
            if bool_col in row and isinstance(row[bool_col], int):
                row[bool_col] = bool(row[bool_col])

    if table == "sweep_findings":
        if "dismissed" in row and isinstance(row["dismissed"], int):
            row["dismissed"] = bool(row["dismissed"])

    # Parse JSON string columns into actual objects for jsonb columns
    for col in ("data", "open_questions", "applied_changes", "metadata",
                "merged_data", "content"):
        if col in row and isinstance(row[col], str):
            try:
                row[col] = json.loads(row[col])
            except (json.JSONDecodeError, ValueError):
                pass  # Keep as string if not valid JSON

    return row


def _upsert_batch(
    client: Any,
    table: str,
    rows: list[dict],
    dry_run: bool,
) -> list[dict]:
    """Upsert a batch of rows. Returns response data (for ID mapping)."""
    if dry_run:
        print(f"    [DRY RUN] Would upsert {len(rows)} rows to {table}")
        return []

    # Determine upsert conflict column based on table
    # Tables with text PKs use "id"; identity tables have no PK to conflict on
    if table in IDENTITY_TABLES:
        # For identity tables, just insert (no upsert — IDs are auto-generated)
        resp = client.table(table).insert(rows).execute()
    elif table == "user_settings":
        # user_settings has composite unique on (user_id, key)
        resp = client.table(table).upsert(rows, on_conflict="user_id,key").execute()
    elif table == "google_tokens":
        # google_tokens has composite unique on (user_id, service)
        resp = client.table(table).upsert(rows, on_conflict="user_id,service").execute()
    else:
        resp = client.table(table).upsert(rows).execute()

    return resp.data if resp.data else []


def import_table(
    client: Any,
    table: str,
    data_dir: Path,
    dry_run: bool,
    id_maps: dict[str, dict],
) -> int:
    """Import a single table from its JSON file. Returns row count."""
    json_file = data_dir / f"{table}.json"
    if not json_file.exists():
        print(f"  {table}: SKIPPED (no file)")
        return 0

    rows = json.loads(json_file.read_text())
    if not rows:
        print(f"  {table}: 0 rows (empty)")
        return 0

    # Transform rows
    transformed = []
    old_ids = []  # Track old IDs for identity tables
    for row in rows:
        old_id = row.get("id")
        result = _transform_row(table, row, id_maps)
        if result is not None:
            transformed.append(result)
            old_ids.append(old_id)

    if not transformed:
        print(f"  {table}: 0 rows after transform")
        return 0

    # Batch upsert
    total_imported = 0
    all_response_data: list[dict] = []
    for i in range(0, len(transformed), BATCH_SIZE):
        batch = transformed[i : i + BATCH_SIZE]
        resp_data = _upsert_batch(client, table, batch, dry_run)
        all_response_data.extend(resp_data)
        total_imported += len(batch)

    # Build ID mapping for identity tables (old SQLite id → new Supabase id)
    if table in IDENTITY_TABLES and all_response_data and not dry_run:
        id_map: dict = {}
        for j, resp_row in enumerate(all_response_data):
            if j < len(old_ids) and "id" in resp_row:
                id_map[old_ids[j]] = resp_row["id"]
        id_maps[table] = id_map

    print(f"  {table}: {total_imported} rows")
    return total_imported


def import_vectors(
    client: Any, data_dir: Path, dry_run: bool
) -> int:
    """Import vector embeddings into things.embedding column.

    Updates existing things rows with their embedding vectors.
    """
    vectors_file = data_dir / "vectors.json"
    if not vectors_file.exists():
        print("  vectors: SKIPPED (no file)")
        return 0

    vectors = json.loads(vectors_file.read_text())
    if not vectors:
        print("  vectors: 0 embeddings")
        return 0

    count = 0
    for vec in vectors:
        thing_id = vec.get("id")
        embedding = vec.get("embedding")
        if not thing_id or not embedding:
            continue

        if dry_run:
            count += 1
            continue

        # Update the things row with the embedding vector
        # pgvector expects array format: [0.1, 0.2, ...]
        try:
            client.table("things").update(  # type: ignore[union-attr]
                {"embedding": embedding}
            ).eq("id", thing_id).execute()
            count += 1
        except Exception as exc:
            print(f"    WARNING: Failed to set embedding for {thing_id}: {exc}")

    label = "[DRY RUN] " if dry_run else ""
    print(f"  vectors: {label}{count} embeddings imported")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import migration JSON into Supabase")
    parser.add_argument(
        "--dir", default="data/migration_export", help="Export directory"
    )
    parser.add_argument("--supabase-url", default=None, help="Supabase project URL")
    parser.add_argument("--supabase-key", default=None, help="Supabase anon key")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview import without writing to Supabase",
    )
    args = parser.parse_args()

    data_dir = Path(args.dir)
    if not data_dir.exists():
        print(f"ERROR: Export directory not found at {data_dir}")
        sys.exit(1)

    manifest_file = data_dir / "manifest.json"
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text())
        print("Source manifest:")
        for t, c in manifest.get("tables", {}).items():
            print(f"  {t}: {c} rows")
        vec_count = manifest.get("vectors", {}).get("count", 0)
        if vec_count:
            print(f"  vectors: {vec_count} embeddings")
        print()

    # Get Supabase credentials
    supabase_url = args.supabase_url or os.environ.get("SUPABASE_URL", "")
    supabase_key = args.supabase_key or os.environ.get("SUPABASE_KEY", "")

    client = None
    if not args.dry_run:
        if not supabase_url or not supabase_key:
            print("ERROR: SUPABASE_URL and SUPABASE_KEY required (env vars or --flags)")
            sys.exit(1)

        from supabase import create_client  # type: ignore[attr-defined]

        client = create_client(supabase_url, supabase_key)
        print(f"Connected to Supabase: {supabase_url}\n")

    # Import tables in order
    print("Importing tables...")
    id_maps: dict[str, dict] = {}
    total = 0
    for table in IMPORT_ORDER:
        count = import_table(client, table, data_dir, args.dry_run, id_maps)
        total += count

    # Import vectors
    print("\nImporting vectors...")
    vec_count = import_vectors(client, data_dir, args.dry_run)

    print(f"\nImport complete: {total} rows + {vec_count} embeddings")


if __name__ == "__main__":
    main()
