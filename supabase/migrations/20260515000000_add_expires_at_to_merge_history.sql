-- Add expires_at column to merge_history (issue #1136)
alter table merge_history add column if not exists expires_at timestamptz;
