-- supabase/rls_policies.sql
-- Run once in Supabase SQL Editor after schema creation.
-- These policies enforce the same (user_id = X OR user_id IS NULL) logic as app code.

-- IMPORTANT: These policies use current_setting('app.user_id', true) for
-- user identity. They are decorative until the application sets this
-- variable at session open time:
--     SET LOCAL app.user_id = '<uid>';
-- This wiring is deferred to Task 6 (Supabase Auth). Until then, the app
-- connects as a service role (RLS bypassed) so there is no security gap.

-- Enable pgvector extension (may already be enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- === things ===
ALTER TABLE things ENABLE ROW LEVEL SECURITY;
CREATE POLICY "things_user_isolation" ON things
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === chat_sessions ===
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "chat_sessions_user_isolation" ON chat_sessions
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === chat_history ===
ALTER TABLE chat_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "chat_history_user_isolation" ON chat_history
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === user_settings ===
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_settings_user_isolation" ON user_settings
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === sweep_findings ===
ALTER TABLE sweep_findings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "sweep_findings_user_isolation" ON sweep_findings
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === sweep_runs ===
ALTER TABLE sweep_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "sweep_runs_user_isolation" ON sweep_runs
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === google_tokens ===
ALTER TABLE google_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY "google_tokens_user_isolation" ON google_tokens
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === merge_history ===
ALTER TABLE merge_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "merge_history_user_isolation" ON merge_history
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === morning_briefings ===
ALTER TABLE morning_briefings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "morning_briefings_user_isolation" ON morning_briefings
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === connection_suggestions ===
ALTER TABLE connection_suggestions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "connection_suggestions_user_isolation" ON connection_suggestions
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === conversation_summaries ===
ALTER TABLE conversation_summaries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "conversation_summaries_user_isolation" ON conversation_summaries
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === weekly_briefings ===
ALTER TABLE weekly_briefings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "weekly_briefings_user_isolation" ON weekly_briefings
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === scheduled_tasks ===
ALTER TABLE scheduled_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "scheduled_tasks_user_isolation" ON scheduled_tasks
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === usage_log ===
ALTER TABLE usage_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "usage_log_user_isolation" ON usage_log
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === nudge_dismissals ===
ALTER TABLE nudge_dismissals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "nudge_dismissals_user_isolation" ON nudge_dismissals
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- === nudge_suppressions ===
ALTER TABLE nudge_suppressions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "nudge_suppressions_user_isolation" ON nudge_suppressions
  FOR ALL USING (user_id IS NULL OR user_id = current_setting('app.user_id', true));

-- Tables WITHOUT user isolation (global/shared):
-- thing_types        (global)
-- thing_relationships (scoped via thing_id FK)
-- thing_embeddings    (scoped via thing_id FK)
-- chat_message_usage  (scoped via chat_message_id FK)
-- users               (identity table)
-- mcp_mutations       (audit log, no user_id)
