# Supabase Cutover Runbook

## Prerequisites

- Supabase project created; `DATABASE_URL` (PostgreSQL connection string) available
- `alembic upgrade head` run against Supabase (creates schema)
- `supabase/rls_policies.sql` run in Supabase SQL Editor

## Cutover Steps (brief downtime)

0. **Navigate to project root**: `cd /home/asiri/gt/reli/mayor/rig`
1. **Stop the server**: `docker compose stop reli`
2. **Export** (run on the host, not inside the container): `DATABASE_URL=sqlite:///data/reli.db python scripts/export_sqlite.py`
3. **Import**: `DATABASE_URL=postgresql://... STORAGE_BACKEND=supabase python scripts/import_supabase.py`
4. **Verify row counts**: compare `export/*.json` line counts against Supabase dashboard
5. **Set env vars**: add `DATABASE_URL=postgresql://...` and `STORAGE_BACKEND=supabase` to `.env`
6. **Start server**: `docker compose up -d reli`
7. **Smoke test**: log in, view Things list, create a Thing, run a chat, run a search

## Rollback

1. Remove `DATABASE_URL` and `STORAGE_BACKEND` from `.env`
2. `docker compose restart reli`

SQLite data is untouched — the export script only reads, never writes.
