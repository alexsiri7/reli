-- Vector search RPC functions for pgvector
-- Part of #189: Replace ChromaDB with pgvector

-- match_things: cosine similarity search over thing embeddings
create or replace function match_things(
    query_embedding vector(3072),
    match_count int default 20,
    filter_active boolean default true,
    filter_type_hint text default null,
    filter_user_id text default null
)
returns table (
    id text,
    distance float
)
language plpgsql
as $$
begin
    return query
    select
        t.id,
        (t.embedding <=> query_embedding)::float as distance
    from things t
    where t.embedding is not null
        and (not filter_active or t.active = true)
        and (filter_type_hint is null or t.type_hint = filter_type_hint)
        and (
            filter_user_id is null
            or t.user_id = filter_user_id
            or t.user_id is null
            or t.user_id = ''
        )
    order by t.embedding <=> query_embedding
    limit match_count;
end;
$$;

-- match_things_by_id: find things similar to a given thing (for connection sweep)
create or replace function match_things_by_id(
    thing_id text,
    match_count int default 5,
    filter_active boolean default true,
    filter_user_id text default null
)
returns table (
    id text,
    distance float
)
language plpgsql
as $$
declare
    source_embedding vector(3072);
begin
    select t.embedding into source_embedding
    from things t
    where t.id = thing_id;

    if source_embedding is null then
        return;
    end if;

    return query
    select
        t.id,
        (t.embedding <=> source_embedding)::float as distance
    from things t
    where t.embedding is not null
        and t.id != thing_id
        and (not filter_active or t.active = true)
        and (
            filter_user_id is null
            or t.user_id = filter_user_id
            or t.user_id is null
            or t.user_id = ''
        )
    order by t.embedding <=> source_embedding
    limit match_count;
end;
$$;
