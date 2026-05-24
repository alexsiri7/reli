#!/usr/bin/env python3
"""Export all SQLite tables to JSON for Supabase import.

Usage:
    DATABASE_URL=sqlite:///data/reli.db python scripts/export_sqlite.py
    # Output: export/<table_name>.json for each table
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from backend.db_engine import engine
from backend.db_models import *  # noqa: F401,F403 — registers all SQLModel metadata

OUTPUT_DIR = pathlib.Path("export")
OUTPUT_DIR.mkdir(exist_ok=True)

insp = inspect(engine)
tables = insp.get_table_names()

with engine.connect() as conn:
    for table in tables:
        rows = conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
        data = [dict(row) for row in rows]
        out_path = OUTPUT_DIR / f"{table}.json"
        out_path.write_text(json.dumps(data, default=str, indent=2))
        print(f"  {table}: {len(data)} rows -> {out_path}")

print(f"\nExport complete. {len(tables)} tables written to {OUTPUT_DIR}/")
