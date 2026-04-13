create table if not exists processed_events (
    id uuid primary key default uuid_generate_v4(),
    source text not null,
    event_key text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (source, event_key)
);
