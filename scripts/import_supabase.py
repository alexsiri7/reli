#!/usr/bin/env python3
"""Import SQLite export JSON files into Supabase Postgres.

Usage:
    DATABASE_URL=postgresql://postgres:<pass>@db.<ref>.supabase.co:5432/postgres \
    STORAGE_BACKEND=supabase \
    python scripts/import_supabase.py

Run AFTER: alembic upgrade head (to create tables in Supabase)
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from backend.db_engine import engine

IMPORT_DIR = pathlib.Path(__file__).resolve().parent.parent / "export"

# Import order respects FK dependencies.
TABLE_ORDER = [
    "users",
    "thing_types",
    "things",
    "thing_relationships",
    "thing_embeddings",
    "chat_sessions",
    "chat_history",
    "chat_message_usage",
    "user_settings",
    "sweep_runs",
    "sweep_findings",
    "google_tokens",
    "merge_history",
    "morning_briefings",
    "connection_suggestions",
    "conversation_summaries",
    "weekly_briefings",
    "nudge_dismissals",
    "nudge_suppressions",
    "mcp_mutations",
    "scheduled_tasks",
    "usage_log",
]

insp = inspect(engine)
existing_tables = set(insp.get_table_names())

with engine.begin() as conn:
    current_table = None
    try:
        for table in TABLE_ORDER:
            current_table = table
            json_file = IMPORT_DIR / f"{table}.json"
            if not json_file.exists():
                print(f"  SKIP {table}: no export file")
                continue
            if table not in existing_tables:
                print(f"  SKIP {table}: table not in target DB (run alembic upgrade head first)")
                continue

            rows = json.loads(json_file.read_text())
            if not rows:
                print(f"  {table}: 0 rows (skip)")
                continue

            # Stringify embedding vectors so pgvector accepts them.
            if table == "thing_embeddings":
                for row in rows:
                    if row.get("embedding") is not None:
                        row["embedding"] = str(row["embedding"])

            cols = list(rows[0].keys())
            col_list = ", ".join(cols)
            val_list = ", ".join(f":{c}" for c in cols)
            stmt = text(
                f"INSERT INTO {table} ({col_list}) VALUES ({val_list}) ON CONFLICT DO NOTHING"
            )
            conn.execute(stmt, rows)
            print(f"  {table}: {len(rows)} rows imported")
    except Exception as exc:
        print(f"\nFAILED at table '{current_table}': {exc}", file=sys.stderr)
        print("All changes rolled back. Fix the issue and re-run.", file=sys.stderr)
        raise

print("\nImport complete.")
