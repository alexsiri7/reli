-- Initial schema: convert SQLite DDL to Postgres with pgvector + RLS
-- Part of #189: Supabase project setup

-- =============================================================================
-- Extensions
-- =============================================================================

create extension if not exists "vector" with schema "extensions";
create extension if not exists "uuid-ossp" with schema "extensions";

-- =============================================================================
-- Tables
-- =============================================================================

-- users (referenced by all other tables via user_id)
create table if not exists users (
    id text primary key,
    email text unique not null,
    google_id text unique not null,
    name text not null,
    picture text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

-- thing_types (type taxonomy, no user_id — shared across users)
create table if not exists thing_types (
    id text primary key,
    name text not null unique,
    icon text not null default '📌',
    color text,
    created_at timestamptz default now()
);

-- things (universal entity model)
create table if not exists things (
    id text primary key,
    title text not null,
    type_hint text,
    checkin_date timestamptz,
    priority integer default 3,
    active boolean default true,
    data jsonb,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    surface boolean default true,
    last_referenced timestamptz,
    open_questions jsonb,
    user_id text not null references users(id),
    embedding vector(1536)
);

create index if not exists idx_things_checkin on things(checkin_date);
create index if not exists idx_things_active on things(active);
create index if not exists idx_things_user_id on things(user_id);
create index if not exists idx_things_embedding on things using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- thing_relationships (graph edges)
create table if not exists thing_relationships (
    id text primary key,
    from_thing_id text not null references things(id) on delete cascade,
    to_thing_id text not null references things(id) on delete cascade,
    relationship_type text not null,
    metadata jsonb,
    created_at timestamptz default now(),
    user_id text not null references users(id)
);

create index if not exists idx_rel_from on thing_relationships(from_thing_id);
create index if not exists idx_rel_to on thing_relationships(to_thing_id);
create index if not exists idx_rel_type on thing_relationships(relationship_type);
create index if not exists idx_rel_user_id on thing_relationships(user_id);

-- chat_history (conversation messages)
create table if not exists chat_history (
    id bigint generated always as identity primary key,
    session_id text not null,
    role text not null,
    content text not null,
    applied_changes jsonb,
    prompt_tokens integer default 0,
    completion_tokens integer default 0,
    cost_usd double precision default 0.0,
    api_calls integer default 0,
    model text,
    timestamp timestamptz default now(),
    user_id text not null references users(id)
);

create index if not exists idx_chat_session on chat_history(session_id);
create index if not exists idx_chat_history_user_id on chat_history(user_id);

-- chat_message_usage (token usage per message)
create table if not exists chat_message_usage (
    id bigint generated always as identity primary key,
    chat_message_id bigint not null references chat_history(id) on delete cascade,
    stage text,
    model text not null,
    prompt_tokens integer default 0,
    completion_tokens integer default 0,
    cost_usd double precision default 0.0
);

create index if not exists idx_chat_msg_usage_msg on chat_message_usage(chat_message_id);

-- conversation_summaries (conversation summary storage)
create table if not exists conversation_summaries (
    id text primary key default extensions.uuid_generate_v4()::text,
    session_id text not null,
    summary text not null,
    message_count integer not null default 0,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    user_id text not null references users(id)
);

create index if not exists idx_conv_summary_session on conversation_summaries(session_id);
create index if not exists idx_conv_summary_user_id on conversation_summaries(user_id);

-- sweep_findings (nightly insights)
create table if not exists sweep_findings (
    id text primary key,
    thing_id text references things(id) on delete cascade,
    finding_type text not null,
    message text not null,
    priority integer default 2,
    dismissed boolean default false,
    created_at timestamptz default now(),
    expires_at timestamptz,
    snoozed_until timestamptz,
    user_id text not null references users(id)
);

create index if not exists idx_sweep_active on sweep_findings(dismissed, expires_at);
create index if not exists idx_sweep_thing on sweep_findings(thing_id);
create index if not exists idx_sweep_findings_user_id on sweep_findings(user_id);

-- usage_log (LLM token tracking)
create table if not exists usage_log (
    id bigint generated always as identity primary key,
    session_id text not null,
    model text not null,
    prompt_tokens integer default 0,
    completion_tokens integer default 0,
    cost_usd double precision default 0.0,
    timestamp timestamptz default now(),
    user_id text not null references users(id)
);

create index if not exists idx_usage_log_timestamp on usage_log(timestamp);
create index if not exists idx_usage_log_session on usage_log(session_id);
create index if not exists idx_usage_log_user_id on usage_log(user_id);

-- connection_suggestions (auto-connect feature)
create table if not exists connection_suggestions (
    id text primary key,
    from_thing_id text not null references things(id) on delete cascade,
    to_thing_id text not null references things(id) on delete cascade,
    suggested_relationship_type text not null,
    reason text not null,
    confidence double precision default 0.5,
    status text not null default 'pending',
    created_at timestamptz default now(),
    resolved_at timestamptz,
    user_id text not null references users(id)
);

create index if not exists idx_conn_sugg_status on connection_suggestions(status);
create index if not exists idx_conn_sugg_from on connection_suggestions(from_thing_id);
create index if not exists idx_conn_sugg_to on connection_suggestions(to_thing_id);
create index if not exists idx_conn_sugg_user_id on connection_suggestions(user_id);

-- google_tokens (OAuth token storage)
create table if not exists google_tokens (
    id bigint generated always as identity primary key,
    user_id text not null references users(id),
    service text not null default 'calendar',
    access_token text not null,
    refresh_token text,
    token_uri text not null,
    client_id text not null,
    client_secret text not null,
    expiry text,
    scopes text,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(user_id, service)
);

create index if not exists idx_google_tokens_user_id on google_tokens(user_id);

-- user_settings (per-user configuration)
create table if not exists user_settings (
    id bigint generated always as identity primary key,
    user_id text not null references users(id),
    key text not null,
    value text,
    updated_at timestamptz default now(),
    unique(user_id, key)
);

create index if not exists idx_user_settings_user on user_settings(user_id);

-- merge_history (audit trail for thing merges)
create table if not exists merge_history (
    id text primary key,
    keep_id text not null,
    remove_id text not null,
    keep_title text not null,
    remove_title text not null,
    merged_data jsonb,
    triggered_by text not null default 'api',
    user_id text references users(id),
    created_at timestamptz default now()
);

create index if not exists idx_merge_history_keep on merge_history(keep_id);
create index if not exists idx_merge_history_created on merge_history(created_at);
create index if not exists idx_merge_history_user on merge_history(user_id);

-- sweep_runs (sweep execution history)
create table if not exists sweep_runs (
    id text primary key,
    user_id text references users(id),
    status text not null default 'running',
    candidates_found integer default 0,
    findings_created integer default 0,
    model text,
    prompt_tokens integer default 0,
    completion_tokens integer default 0,
    cost_usd double precision default 0.0,
    error text,
    started_at timestamptz not null,
    completed_at timestamptz
);

create index if not exists idx_sweep_runs_user on sweep_runs(user_id);
create index if not exists idx_sweep_runs_started on sweep_runs(started_at);

-- morning_briefings (pre-generated briefing storage)
create table if not exists morning_briefings (
    id text primary key,
    user_id text references users(id),
    briefing_date text not null,
    content jsonb not null,
    generated_at timestamptz not null,
    unique(user_id, briefing_date)
);

create index if not exists idx_morning_briefings_user on morning_briefings(user_id);
create index if not exists idx_morning_briefings_date on morning_briefings(briefing_date);

-- =============================================================================
-- Seed data: default thing types
-- =============================================================================

insert into thing_types (id, name, icon, color) values
    ('task', 'task', '📋', null),
    ('note', 'note', '📝', null),
    ('project', 'project', '📁', null),
    ('idea', 'idea', '💡', null),
    ('goal', 'goal', '🎯', null),
    ('journal', 'journal', '📓', null),
    ('person', 'person', '👤', null),
    ('place', 'place', '📍', null),
    ('event', 'event', '📅', null),
    ('concept', 'concept', '🧠', null),
    ('reference', 'reference', '🔗', null)
on conflict (id) do nothing;

-- =============================================================================
-- Row Level Security (RLS) policies
-- =============================================================================

-- Helper: auth.uid() returns the authenticated user's UUID in Supabase.
-- Our users.id is text, so we cast auth.uid() to text for comparison.

-- users
alter table users enable row level security;

create policy "Users can read own profile"
    on users for select
    using (id = auth.uid()::text);

create policy "Users can update own profile"
    on users for update
    using (id = auth.uid()::text);

-- things
alter table things enable row level security;

create policy "Users can select own things"
    on things for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own things"
    on things for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own things"
    on things for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own things"
    on things for delete
    using (user_id = auth.uid()::text);

-- thing_relationships
alter table thing_relationships enable row level security;

create policy "Users can select own relationships"
    on thing_relationships for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own relationships"
    on thing_relationships for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own relationships"
    on thing_relationships for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own relationships"
    on thing_relationships for delete
    using (user_id = auth.uid()::text);

-- chat_history
alter table chat_history enable row level security;

create policy "Users can select own chat history"
    on chat_history for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own chat history"
    on chat_history for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own chat history"
    on chat_history for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own chat history"
    on chat_history for delete
    using (user_id = auth.uid()::text);

-- chat_message_usage (access controlled via chat_history FK)
alter table chat_message_usage enable row level security;

create policy "Users can select own message usage"
    on chat_message_usage for select
    using (
        chat_message_id in (
            select id from chat_history where user_id = auth.uid()::text
        )
    );

create policy "Users can insert own message usage"
    on chat_message_usage for insert
    with check (
        chat_message_id in (
            select id from chat_history where user_id = auth.uid()::text
        )
    );

create policy "Users can delete own message usage"
    on chat_message_usage for delete
    using (
        chat_message_id in (
            select id from chat_history where user_id = auth.uid()::text
        )
    );

-- conversation_summaries
alter table conversation_summaries enable row level security;

create policy "Users can select own summaries"
    on conversation_summaries for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own summaries"
    on conversation_summaries for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own summaries"
    on conversation_summaries for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own summaries"
    on conversation_summaries for delete
    using (user_id = auth.uid()::text);

-- sweep_findings
alter table sweep_findings enable row level security;

create policy "Users can select own findings"
    on sweep_findings for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own findings"
    on sweep_findings for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own findings"
    on sweep_findings for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own findings"
    on sweep_findings for delete
    using (user_id = auth.uid()::text);

-- usage_log
alter table usage_log enable row level security;

create policy "Users can select own usage"
    on usage_log for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own usage"
    on usage_log for insert
    with check (user_id = auth.uid()::text);

-- connection_suggestions
alter table connection_suggestions enable row level security;

create policy "Users can select own suggestions"
    on connection_suggestions for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own suggestions"
    on connection_suggestions for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own suggestions"
    on connection_suggestions for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own suggestions"
    on connection_suggestions for delete
    using (user_id = auth.uid()::text);

-- google_tokens
alter table google_tokens enable row level security;

create policy "Users can select own tokens"
    on google_tokens for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own tokens"
    on google_tokens for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own tokens"
    on google_tokens for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own tokens"
    on google_tokens for delete
    using (user_id = auth.uid()::text);

-- user_settings
alter table user_settings enable row level security;

create policy "Users can select own settings"
    on user_settings for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own settings"
    on user_settings for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own settings"
    on user_settings for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own settings"
    on user_settings for delete
    using (user_id = auth.uid()::text);

-- merge_history
alter table merge_history enable row level security;

create policy "Users can select own merge history"
    on merge_history for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own merge history"
    on merge_history for insert
    with check (user_id = auth.uid()::text);

-- sweep_runs
alter table sweep_runs enable row level security;

create policy "Users can select own sweep runs"
    on sweep_runs for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own sweep runs"
    on sweep_runs for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own sweep runs"
    on sweep_runs for update
    using (user_id = auth.uid()::text);

-- morning_briefings
alter table morning_briefings enable row level security;

create policy "Users can select own briefings"
    on morning_briefings for select
    using (user_id = auth.uid()::text);

create policy "Users can insert own briefings"
    on morning_briefings for insert
    with check (user_id = auth.uid()::text);

create policy "Users can update own briefings"
    on morning_briefings for update
    using (user_id = auth.uid()::text);

create policy "Users can delete own briefings"
    on morning_briefings for delete
    using (user_id = auth.uid()::text);

-- thing_types: readable by all authenticated users (shared taxonomy)
alter table thing_types enable row level security;

create policy "Authenticated users can read thing types"
    on thing_types for select
    using (auth.uid() is not null);

-- =============================================================================
-- Updated_at trigger function
-- =============================================================================

create or replace function update_updated_at_column()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger set_updated_at_users
    before update on users
    for each row execute function update_updated_at_column();

create trigger set_updated_at_things
    before update on things
    for each row execute function update_updated_at_column();

create trigger set_updated_at_google_tokens
    before update on google_tokens
    for each row execute function update_updated_at_column();

create trigger set_updated_at_user_settings
    before update on user_settings
    for each row execute function update_updated_at_column();

create trigger set_updated_at_conversation_summaries
    before update on conversation_summaries
    for each row execute function update_updated_at_column();
