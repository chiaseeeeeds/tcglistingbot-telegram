alter table if exists pokemon_sets
    add column if not exists symbol_image_url text,
    add column if not exists logo_image_url text;

create index if not exists idx_pokemon_sets_symbol_image_url
    on pokemon_sets(symbol_image_url);
