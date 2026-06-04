-- Add confidence, context_snapshot, and dismissed_reason columns to sweep_findings
-- Fixes missing columns introduced in alembic migrations m7n8o9p0q1r2 and o9p0q1r2s3t4
-- Part of #1150

alter table sweep_findings add column if not exists confidence double precision default 0.5;
alter table sweep_findings add column if not exists context_snapshot jsonb;
alter table sweep_findings add column if not exists dismissed_reason text;
