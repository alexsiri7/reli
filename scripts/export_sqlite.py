#!/usr/bin/env python3
"""Export SQLite + ChromaDB data to JSON for Supabase import.

Usage:
    python scripts/export_sqlite.py [--output-dir OUTPUT_DIR]

Outputs one JSON file per table in OUTPUT_DIR (default: ./export/):
    tables/*.json   — one JSON array per SQLite table
    embeddings.json — {thing_id: [float, ...], ...} from ChromaDB

Part of #189: Supabase migration (Task 5 — export script).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Resolve project root (two levels up from this script)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _get_db_path() -> Path:
    data_dir = os.environ.get("DATA_DIR", str(PROJECT_ROOT / "backend"))
    return Path(data_dir) / "reli.db"


def export_sqlite(db_path: Path, output_dir: Path) -> None:
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row["name"] for row in cursor.fetchall()]
    logger.info("Found %d tables: %s", len(tables), tables)

    total_rows = 0
    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        data = [dict(r) for r in rows]
        out_file = tables_dir / f"{table}.json"
        out_file.write_text(json.dumps(data, indent=2, default=str))
        logger.info("  %s: %d rows → %s", table, len(data), out_file)
        total_rows += len(data)

    conn.close()
    logger.info("SQLite export complete: %d total rows across %d tables", total_rows, len(tables))


def export_chromadb(output_dir: Path) -> None:
    try:
        import chromadb
    except ImportError:
        logger.warning("chromadb not installed — skipping embedding export")
        return

    from backend.config import settings

    chroma_path = Path(settings.DATA_DIR) / "chroma_db"
    if not chroma_path.exists():
        logger.warning("ChromaDB path not found: %s — skipping embedding export", chroma_path)
        return

    try:
        client = chromadb.PersistentClient(
            path=str(chroma_path),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        collection = client.get_collection("things")
        result = collection.get(include=["embeddings"])
        ids = result["ids"]
        embeddings = result["embeddings"]
        if embeddings is None:
            logger.warning("ChromaDB returned no embeddings")
            return

        mapping = {id_: emb for id_, emb in zip(ids, embeddings, strict=False)}
        out_file = output_dir / "embeddings.json"
        out_file.write_text(json.dumps(mapping, indent=2))
        logger.info("ChromaDB export complete: %d embeddings → %s", len(mapping), out_file)
    except Exception as exc:
        logger.error("ChromaDB export failed: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export SQLite + ChromaDB to JSON")
    parser.add_argument("--output-dir", default="export", help="Directory to write export files")
    parser.add_argument("--db-path", help="Path to reli.db (default: auto-detect via DATA_DIR)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = Path(args.db_path) if args.db_path else _get_db_path()
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    logger.info("Exporting from: %s", db_path)
    logger.info("Output directory: %s", output_dir.resolve())

    export_sqlite(db_path, output_dir)
    export_chromadb(output_dir)

    logger.info("Export complete. Next step: run scripts/import_supabase.py --input-dir %s", output_dir)


if __name__ == "__main__":
    main()
