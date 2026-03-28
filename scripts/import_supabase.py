#!/usr/bin/env python3
"""Import exported SQLite/ChromaDB JSON data into Supabase.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python scripts/import_supabase.py [--input-dir INPUT_DIR]

Reads from INPUT_DIR (default: ./export/):
    tables/*.json   — one JSON array per table, imported via Supabase PostgREST
    embeddings.json — {thing_id: [float, ...]} applied to things.embedding

Import order respects FK constraints:
    users → thing_types → things → thing_relationships → chat_history →
    chat_message_usage → conversation_summaries → sweep_findings → usage_log →
    connection_suggestions → google_tokens → user_settings → merge_history →
    sweep_runs → morning_briefings

Part of #189: Supabase migration (Task 5 — import script).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import order respects FK dependencies
_TABLE_ORDER = [
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

# Chunk size for batch inserts (PostgREST has a payload limit)
_CHUNK_SIZE = 500


def _chunk(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def import_tables(client, input_dir: Path) -> None:
    tables_dir = input_dir / "tables"
    if not tables_dir.exists():
        logger.error("tables/ directory not found in %s", input_dir)
        sys.exit(1)

    available = {p.stem for p in tables_dir.glob("*.json")}
    ordered = [t for t in _TABLE_ORDER if t in available]
    extra = available - set(_TABLE_ORDER)
    if extra:
        logger.warning("Unknown tables in export (will import last): %s", sorted(extra))
        ordered.extend(sorted(extra))

    for table in ordered:
        json_file = tables_dir / f"{table}.json"
        rows = json.loads(json_file.read_text())
        if not rows:
            logger.info("  %s: 0 rows — skipping", table)
            continue

        logger.info("  %s: importing %d rows …", table, len(rows))
        inserted = 0
        errors = 0
        for chunk in _chunk(rows, _CHUNK_SIZE):
            try:
                client.table(table).upsert(chunk, on_conflict="id").execute()
                inserted += len(chunk)
            except Exception as exc:
                logger.error("    chunk failed for %s: %s", table, exc)
                errors += len(chunk)
        logger.info("    %s: %d inserted, %d errors", table, inserted, errors)


def import_embeddings(client, input_dir: Path) -> None:
    emb_file = input_dir / "embeddings.json"
    if not emb_file.exists():
        logger.info("embeddings.json not found — skipping embedding import")
        return

    mapping: dict[str, list[float]] = json.loads(emb_file.read_text())
    logger.info("Importing %d embeddings into things.embedding …", len(mapping))

    count = 0
    errors = 0
    for thing_id, embedding in mapping.items():
        try:
            client.table("things").update({"embedding": embedding}).eq("id", thing_id).execute()
            count += 1
        except Exception as exc:
            logger.error("  embedding update failed for %s: %s", thing_id, exc)
            errors += 1

    logger.info("Embeddings: %d updated, %d errors", count, errors)


def verify(client) -> None:
    logger.info("Verification — row counts:")
    for table in _TABLE_ORDER:
        try:
            resp = client.table(table).select("*", count="exact").limit(0).execute()
            logger.info("  %s: %d rows", table, resp.count or 0)
        except Exception as exc:
            logger.warning("  %s: could not count — %s", table, exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import exported JSON into Supabase")
    parser.add_argument("--input-dir", default="export", help="Directory with export files")
    parser.add_argument("--skip-embeddings", action="store_true", help="Skip embedding import")
    parser.add_argument("--verify-only", action="store_true", help="Only print row counts, no import")
    args = parser.parse_args()

    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY", "")
    if not supabase_url or not supabase_key:
        logger.error("SUPABASE_URL and SUPABASE_KEY must be set")
        sys.exit(1)

    try:
        from supabase import create_client
    except ImportError:
        logger.error("supabase-py not installed — run: pip install supabase")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)
    input_dir = Path(args.input_dir)

    if args.verify_only:
        verify(client)
        return

    if not input_dir.exists():
        logger.error("Input directory not found: %s", input_dir)
        sys.exit(1)

    logger.info("Importing from: %s", input_dir.resolve())
    import_tables(client, input_dir)

    if not args.skip_embeddings:
        import_embeddings(client, input_dir)

    verify(client)
    logger.info("Import complete.")


if __name__ == "__main__":
    main()
