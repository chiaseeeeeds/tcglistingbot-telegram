create table if not exists pokemon_sets (
    id uuid primary key default uuid_generate_v4(),
    language text not null default 'en',
    series_name text,
    set_number text,
    set_name text not null,
    set_code text,
    expansion_type text,
    card_count integer,
    release_date date,
    source_url text,
    source_name text not null default 'bulbapedia',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (language, set_name)
);

create index if not exists idx_pokemon_sets_code on pokemon_sets(set_code);

create table if not exists pokemon_cards_staging (
    id uuid primary key default uuid_generate_v4(),
    language text not null default 'en',
    series_name text,
    set_name text not null,
    set_code text,
    card_name text not null,
    card_number text not null,
    printed_total text,
    rarity text,
    variant text not null default '',
    source_file text not null,
    source_url text,
    source_name text not null default 'pokemon-card-csv',
    raw_payload jsonb not null,
    normalized_card_id uuid references cards(id),
    import_batch_id text,
    imported_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (language, set_name, card_name, card_number, variant)
);

create index if not exists idx_pokemon_cards_staging_set_code_number
    on pokemon_cards_staging(set_code, card_number);

alter table pokemon_sets enable row level security;
alter table pokemon_cards_staging enable row level security;

drop trigger if exists update_pokemon_sets_updated_at on pokemon_sets;
create trigger update_pokemon_sets_updated_at before update on pokemon_sets
for each row execute function update_updated_at_column();

drop trigger if exists update_pokemon_cards_staging_updated_at on pokemon_cards_staging;
create trigger update_pokemon_cards_staging_updated_at before update on pokemon_cards_staging
for each row execute function update_updated_at_column();
