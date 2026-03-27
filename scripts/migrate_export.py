#!/usr/bin/env python3
"""Export all SQLite tables and ChromaDB vectors to JSON for Supabase migration.

Usage:
    python scripts/migrate_export.py [--db PATH] [--chroma PATH] [--out DIR]

Defaults:
    --db      data/reli.db
    --chroma  data/chroma_db  (or backend/chroma_db)
    --out     data/migration_export/

Produces one JSON file per table, plus vectors.json for ChromaDB embeddings.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Ensure backend is importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _serialize_row(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a JSON-safe dict."""
    d = dict(row)
    for k, v in d.items():
        # sqlite3 returns bytes for BLOBs — skip or base64-encode
        if isinstance(v, bytes):
            d[k] = None  # vectors handled separately via ChromaDB
    return d


def export_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    """Export all rows from a SQLite table."""
    cursor = conn.execute(f"SELECT * FROM [{table}]")  # noqa: S608
    return [_serialize_row(row) for row in cursor.fetchall()]


def export_chromadb_vectors(chroma_path: Path) -> list[dict]:
    """Export all vectors + metadata from ChromaDB.

    Returns list of dicts with keys: id, embedding, document, metadata.
    """
    try:
        # Suppress posthog telemetry (same as vector_store.py)
        import types

        if "posthog" not in sys.modules:
            stub = types.ModuleType("posthog")
            stub.capture = lambda *a, **k: None  # type: ignore[attr-defined]
            stub.disabled = True  # type: ignore[attr-defined]
            stub.project_api_key = ""  # type: ignore[attr-defined]
            sys.modules["posthog"] = stub

        import chromadb

        client = chromadb.PersistentClient(
            path=str(chroma_path),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(name="things")
        result = collection.get(include=["embeddings", "documents", "metadatas"])  # type: ignore[list-item]

        vectors = []
        ids = result.get("ids") or []
        embeddings = result.get("embeddings") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []

        for i, id_ in enumerate(ids):
            vec: dict = {"id": id_}
            if i < len(embeddings) and embeddings[i] is not None:
                vec["embedding"] = embeddings[i]
            if i < len(documents) and documents[i] is not None:
                vec["document"] = documents[i]
            if i < len(metadatas) and metadatas[i] is not None:
                vec["metadata"] = metadatas[i]
            vectors.append(vec)

        return vectors
    except Exception as exc:
        print(f"WARNING: ChromaDB export failed ({exc}). Skipping vectors.")
        return []


# Tables in dependency order (parents before children).
EXPORT_TABLES = [
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Export SQLite + ChromaDB to JSON")
    parser.add_argument("--db", default="data/reli.db", help="Path to SQLite database")
    parser.add_argument("--chroma", default=None, help="Path to ChromaDB directory")
    parser.add_argument(
        "--out", default="data/migration_export", help="Output directory"
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    # Resolve ChromaDB path — try data/chroma_db first, then backend/chroma_db
    if args.chroma:
        chroma_path = Path(args.chroma)
    elif Path("data/chroma_db").exists():
        chroma_path = Path("data/chroma_db")
    elif Path("backend/chroma_db").exists():
        chroma_path = Path("backend/chroma_db")
    else:
        chroma_path = None

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Connect to SQLite
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    manifest: dict = {"tables": {}, "vectors": {"count": 0}}

    # Export each table
    for table in EXPORT_TABLES:
        try:
            rows = export_table(conn, table)
            out_file = out_dir / f"{table}.json"
            out_file.write_text(json.dumps(rows, indent=2, default=str))
            manifest["tables"][table] = len(rows)
            print(f"  {table}: {len(rows)} rows")
        except Exception as exc:
            print(f"  {table}: SKIPPED ({exc})")
            manifest["tables"][table] = 0

    conn.close()

    # Export ChromaDB vectors
    if chroma_path and chroma_path.exists():
        print(f"\nExporting ChromaDB vectors from {chroma_path}...")
        vectors = export_chromadb_vectors(chroma_path)
        out_file = out_dir / "vectors.json"
        out_file.write_text(json.dumps(vectors, indent=2, default=str))
        manifest["vectors"]["count"] = len(vectors)
        print(f"  vectors: {len(vectors)} embeddings")
    else:
        print("\nNo ChromaDB directory found — skipping vector export.")

    # Write manifest
    manifest_file = out_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))
    print(f"\nExport complete → {out_dir}/")
    print(f"Manifest: {manifest_file}")


if __name__ == "__main__":
    main()
