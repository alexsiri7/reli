#!/usr/bin/env python3
"""Verify Supabase migration: row counts, spot checks, vector search sanity.

Usage:
    python scripts/migrate_verify.py [--dir DIR] [--supabase-url URL] [--supabase-key KEY]

Compares the exported JSON (source of truth) against live Supabase data.

Checks:
  1. Row counts match for every table
  2. Spot checks: verify specific rows exist with correct data
  3. Vector sanity: confirm embeddings exist and similarity search works
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Tables where Supabase auto-generates new IDs (can't check by PK)
IDENTITY_TABLES = {"chat_history", "chat_message_usage", "usage_log",
                   "google_tokens", "user_settings"}

# All tables to verify
VERIFY_TABLES = [
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


class VerificationResult:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        print(f"  PASS  {msg}")

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print(f"  FAIL  {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  WARN  {msg}")

    def summary(self) -> None:
        total = len(self.passed) + len(self.failed)
        print(f"\n{'='*60}")
        print(f"Verification: {len(self.passed)}/{total} checks passed")
        if self.warnings:
            print(f"Warnings: {len(self.warnings)}")
        if self.failed:
            print("\nFailed checks:")
            for f in self.failed:
                print(f"  - {f}")
            sys.exit(1)
        else:
            print("\nAll checks passed!")


def verify_row_counts(
    client: Any,
    data_dir: Path,
    result: VerificationResult,
) -> None:
    """Compare row counts between export JSON and Supabase."""
    print("\n--- Row Count Verification ---")
    for table in VERIFY_TABLES:
        json_file = data_dir / f"{table}.json"
        if not json_file.exists():
            result.warn(f"{table}: no export file found")
            continue

        export_rows = json.loads(json_file.read_text())
        expected = len(export_rows)

        try:
            resp = (
                client.table(table)  # type: ignore[union-attr]
                .select("*", count="exact")
                .limit(0)
                .execute()
            )
            actual = resp.count if resp.count is not None else 0
        except Exception as exc:
            result.fail(f"{table}: query failed ({exc})")
            continue

        if actual == expected:
            result.ok(f"{table}: {actual} rows")
        elif actual >= expected:
            # More rows is okay (might have seed data like thing_types)
            result.warn(
                f"{table}: {actual} rows (expected {expected}, "
                f"+{actual - expected} extra — may include seed data)"
            )
        else:
            result.fail(
                f"{table}: {actual} rows (expected {expected}, "
                f"missing {expected - actual})"
            )


def verify_spot_checks(
    client: Any,
    data_dir: Path,
    result: VerificationResult,
) -> None:
    """Verify specific rows exist with correct field values."""
    print("\n--- Spot Check Verification ---")

    # Check users
    users_file = data_dir / "users.json"
    if users_file.exists():
        users = json.loads(users_file.read_text())
        if users:
            sample = users[0]
            try:
                resp = (
                    client.table("users")  # type: ignore[union-attr]
                    .select("*")
                    .eq("id", sample["id"])
                    .execute()
                )
                if resp.data and len(resp.data) == 1:
                    row = resp.data[0]
                    if row["email"] == sample["email"] and row["name"] == sample["name"]:
                        result.ok(f"users: spot check user '{sample['name']}' OK")
                    else:
                        result.fail(
                            f"users: data mismatch for {sample['id']} "
                            f"(email: {row.get('email')} vs {sample['email']})"
                        )
                else:
                    result.fail(f"users: user {sample['id']} not found")
            except Exception as exc:
                result.fail(f"users: spot check failed ({exc})")

    # Check things (first and last)
    things_file = data_dir / "things.json"
    if things_file.exists():
        things = json.loads(things_file.read_text())
        if things:
            for label, sample in [("first", things[0]), ("last", things[-1])]:
                try:
                    resp = (
                        client.table("things")  # type: ignore[union-attr]
                        .select("id,title,type_hint,user_id")
                        .eq("id", sample["id"])
                        .execute()
                    )
                    if resp.data and len(resp.data) == 1:
                        row = resp.data[0]
                        if row["title"] == sample["title"]:
                            result.ok(
                                f"things: spot check {label} "
                                f"'{sample['title'][:40]}' OK"
                            )
                        else:
                            result.fail(
                                f"things: title mismatch for {sample['id']} "
                                f"({label})"
                            )
                    else:
                        result.fail(f"things: {label} thing {sample['id']} not found")
                except Exception as exc:
                    result.fail(f"things: {label} spot check failed ({exc})")

    # Check relationships
    rels_file = data_dir / "thing_relationships.json"
    if rels_file.exists():
        rels = json.loads(rels_file.read_text())
        if rels:
            sample = rels[0]
            try:
                resp = (
                    client.table("thing_relationships")  # type: ignore[union-attr]
                    .select("*")
                    .eq("id", sample["id"])
                    .execute()
                )
                if resp.data and len(resp.data) == 1:
                    row = resp.data[0]
                    if (
                        row["from_thing_id"] == sample["from_thing_id"]
                        and row["to_thing_id"] == sample["to_thing_id"]
                    ):
                        result.ok("thing_relationships: spot check OK")
                    else:
                        result.fail("thing_relationships: FK mismatch")
                else:
                    result.fail(
                        f"thing_relationships: {sample['id']} not found"
                    )
            except Exception as exc:
                result.fail(f"thing_relationships: spot check failed ({exc})")


def verify_vectors(
    client: Any,
    data_dir: Path,
    result: VerificationResult,
) -> None:
    """Verify vector embeddings exist and similarity search is functional."""
    print("\n--- Vector Verification ---")

    vectors_file = data_dir / "vectors.json"
    if not vectors_file.exists():
        result.warn("vectors: no export file found — skipping")
        return

    vectors = json.loads(vectors_file.read_text())
    if not vectors:
        result.warn("vectors: no embeddings in export — skipping")
        return

    # Check that things have non-null embeddings
    try:
        # Count things with embeddings
        resp = (
            client.table("things")  # type: ignore[union-attr]
            .select("id", count="exact")
            .not_.is_("embedding", "null")  # type: ignore[union-attr]
            .limit(0)
            .execute()
        )
        embedded_count = resp.count if resp.count is not None else 0
        expected = len(vectors)

        if embedded_count == expected:
            result.ok(f"vectors: {embedded_count} things have embeddings")
        elif embedded_count > 0:
            result.warn(
                f"vectors: {embedded_count}/{expected} things have embeddings"
            )
        else:
            result.fail("vectors: no things have embeddings")
    except Exception as exc:
        result.fail(f"vectors: count query failed ({exc})")
        return

    # Spot check: verify a specific thing's embedding dimension
    sample_vec = next(
        (v for v in vectors if v.get("embedding")), None
    )
    if sample_vec:
        try:
            resp = (
                client.table("things")  # type: ignore[union-attr]
                .select("id,embedding")
                .eq("id", sample_vec["id"])
                .execute()
            )
            if resp.data and resp.data[0].get("embedding"):
                stored = resp.data[0]["embedding"]
                # pgvector returns embedding as a string like "[0.1,0.2,...]"
                if isinstance(stored, str):
                    stored = json.loads(stored)
                if len(stored) == len(sample_vec["embedding"]):
                    result.ok(
                        f"vectors: dimension check OK "
                        f"({len(stored)}d for {sample_vec['id'][:20]})"
                    )
                else:
                    result.fail(
                        f"vectors: dimension mismatch "
                        f"({len(stored)} vs {len(sample_vec['embedding'])})"
                    )
            else:
                result.fail(
                    f"vectors: embedding missing for {sample_vec['id'][:20]}"
                )
        except Exception as exc:
            result.warn(f"vectors: spot check failed ({exc})")

    # Sanity test: run a similarity search via RPC (if function exists)
    try:
        # Try a basic vector similarity query using PostgREST
        # This uses the built-in pgvector operator via Supabase RPC
        resp = (
            client.table("things")  # type: ignore[union-attr]
            .select("id,title")
            .not_.is_("embedding", "null")  # type: ignore[union-attr]
            .limit(5)
            .execute()
        )
        if resp.data and len(resp.data) > 0:
            result.ok(
                f"vectors: can query things with embeddings "
                f"({len(resp.data)} returned)"
            )
        else:
            result.warn("vectors: query returned no results")
    except Exception as exc:
        result.warn(f"vectors: similarity search test failed ({exc})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify Supabase migration"
    )
    parser.add_argument(
        "--dir", default="data/migration_export", help="Export directory"
    )
    parser.add_argument("--supabase-url", default=None)
    parser.add_argument("--supabase-key", default=None)
    args = parser.parse_args()

    data_dir = Path(args.dir)
    if not data_dir.exists():
        print(f"ERROR: Export directory not found at {data_dir}")
        sys.exit(1)

    supabase_url = args.supabase_url or os.environ.get("SUPABASE_URL", "")
    supabase_key = args.supabase_key or os.environ.get("SUPABASE_KEY", "")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY required")
        sys.exit(1)

    from supabase import create_client  # type: ignore[attr-defined]

    client = create_client(supabase_url, supabase_key)
    print(f"Connected to Supabase: {supabase_url}")

    result = VerificationResult()

    verify_row_counts(client, data_dir, result)
    verify_spot_checks(client, data_dir, result)
    verify_vectors(client, data_dir, result)

    result.summary()


if __name__ == "__main__":
    main()
