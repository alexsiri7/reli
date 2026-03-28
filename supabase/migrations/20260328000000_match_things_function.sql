-- pgvector similarity search function for Things
-- Called by vector_store.py when STORAGE_BACKEND=supabase
-- Part of #189: Supabase vector search (Task 4)

-- match_things: given a query embedding, return the closest Things by
-- cosine distance (via the <=> operator from pgvector).
--
-- Parameters:
--   query_embedding  — the embedding vector to search against
--   match_count      — maximum number of results to return
--   user_id_filter   — required; only returns Things for this user
--   active_only      — when true, filter out inactive Things
--   type_hint_filter — optional; filter to a specific type_hint value
--
-- Returns rows of (id text, distance float) ordered by ascending distance.

create or replace function match_things(
    query_embedding vector(3072),
    match_count     int,
    user_id_filter  text,
    active_only     bool,
    type_hint_filter text default null
)
returns table (id text, distance float)
language plpgsql
as $$
begin
    return query
    select
        t.id,
        (t.embedding <=> query_embedding)::float as distance
    from things t
    where
        t.embedding is not null
        and t.user_id = user_id_filter
        and (not active_only or t.active = true)
        and (type_hint_filter is null or t.type_hint = type_hint_filter)
    order by t.embedding <=> query_embedding
    limit match_count;
end;
$$;
