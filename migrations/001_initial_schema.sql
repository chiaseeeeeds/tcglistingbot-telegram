create extension if not exists "uuid-ossp";

create table if not exists sellers (
    id uuid primary key default uuid_generate_v4(),
    telegram_id bigint unique not null,
    telegram_username text,
    telegram_display_name text not null,
    reputation_score integer not null default 0,
    total_sales_sgd numeric(10, 2) not null default 0,
    is_active boolean not null default true,
    is_banned boolean not null default false,
    ban_reason text,
    vacation_mode boolean not null default false,
    vacation_until timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists seller_configs (
    id uuid primary key default uuid_generate_v4(),
    seller_id uuid not null references sellers(id) on delete cascade,
    primary_channel_id bigint,
    primary_channel_name text,
    additional_channel_ids bigint[] default '{}',
    seller_display_name text,
    claim_keywords text[] not null default array['claim']::text[],
    payment_methods text[] not null default '{}',
    paynow_identifier text,
    bank_name text,
    bank_account_number text,
    offers_postage boolean not null default true,
    postage_fee_sgd numeric(6, 2) default 0,
    postage_method text default 'Registered Mail',
    postage_bearer text default 'buyer',
    footer_text text default '',
    disclaimer_text text default '',
    template_order jsonb not null default '["title","price","condition","claim_method","payment","postage","footer"]'::jsonb,
    auto_bump_enabled boolean not null default true,
    auto_bump_days integer not null default 3,
    payment_deadline_hours integer not null default 24,
    setup_complete boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (seller_id)
);

create table if not exists cards (
    id uuid primary key default uuid_generate_v4(),
    game text not null,
    set_code text not null,
    set_name text not null,
    card_number text not null,
    card_name_en text not null,
    card_name_jp text,
    variant text,
    rarity text,
    tcgplayer_product_id integer,
    tcgplayer_url text,
    pricecharting_id integer,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    unique (game, set_code, card_number, coalesce(variant, ''))
);

create table if not exists listings (
    id uuid primary key default uuid_generate_v4(),
    seller_id uuid not null references sellers(id),
    card_id uuid references cards(id),
    card_name text not null,
    card_variant text,
    set_name text,
    game text not null,
    listing_type text not null default 'fixed',
    status text not null default 'active',
    price_sgd numeric(8, 2),
    condition_notes text default '',
    custom_description text default '',
    tcgplayer_price_sgd numeric(8, 2),
    pricecharting_price_sgd numeric(8, 2),
    yuyutei_price_sgd numeric(8, 2),
    starting_bid_sgd numeric(8, 2),
    current_bid_sgd numeric(8, 2),
    bid_increment_sgd numeric(6, 2) default 0.50,
    auction_end_time timestamptz,
    anti_snipe_minutes integer default 2,
    primary_image_path text,
    secondary_image_path text,
    posted_channel_id bigint,
    posted_message_id bigint,
    scheduled_post_time timestamptz,
    expires_at timestamptz,
    bump_count integer not null default 0,
    last_bumped_at timestamptz,
    is_cross_posted boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists listing_channels (
    id uuid primary key default uuid_generate_v4(),
    listing_id uuid not null references listings(id) on delete cascade,
    channel_id bigint not null,
    channel_name text,
    message_id bigint not null,
    created_at timestamptz not null default now(),
    unique (listing_id, channel_id)
);

create table if not exists claims (
    id uuid primary key default uuid_generate_v4(),
    listing_id uuid not null references listings(id),
    buyer_telegram_id bigint not null,
    buyer_username text,
    buyer_display_name text,
    status text not null default 'queued',
    queue_position integer not null default 1,
    bid_amount_sgd numeric(8, 2),
    claimed_at timestamptz not null default now(),
    confirmed_at timestamptz,
    payment_deadline timestamptz,
    paid_at timestamptz,
    failed_at timestamptz,
    payment_prompt_sent boolean not null default false,
    payment_prompt_message_id bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists idx_claims_one_confirmed_per_listing
    on claims(listing_id)
    where status in ('confirmed', 'payment_pending');

create table if not exists transactions (
    id uuid primary key default uuid_generate_v4(),
    listing_id uuid not null references listings(id),
    claim_id uuid references claims(id),
    seller_id uuid not null references sellers(id),
    buyer_telegram_id bigint not null,
    buyer_username text,
    buyer_display_name text,
    final_price_sgd numeric(8, 2) not null,
    completed_at timestamptz not null default now(),
    is_disputed boolean not null default false,
    dispute_notes text,
    created_at timestamptz not null default now()
);

create table if not exists strikes (
    id uuid primary key default uuid_generate_v4(),
    telegram_id bigint not null,
    telegram_username text,
    strike_type text not null,
    related_listing_id uuid references listings(id),
    related_claim_id uuid references claims(id),
    notes text,
    reported_by_telegram_id bigint,
    created_at timestamptz not null default now()
);

create table if not exists seller_buyer_blacklist (
    id uuid primary key default uuid_generate_v4(),
    seller_id uuid not null references sellers(id) on delete cascade,
    blocked_telegram_id bigint not null,
    blocked_username text,
    reason text,
    created_at timestamptz not null default now(),
    unique (seller_id, blocked_telegram_id)
);

create table if not exists scheduled_listings (
    id uuid primary key default uuid_generate_v4(),
    seller_id uuid not null references sellers(id),
    listing_draft_json jsonb not null,
    post_at timestamptz not null,
    status text not null default 'pending',
    created_listing_id uuid references listings(id),
    created_at timestamptz not null default now()
);

create or replace function update_updated_at_column()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists update_sellers_updated_at on sellers;
create trigger update_sellers_updated_at before update on sellers
for each row execute function update_updated_at_column();

drop trigger if exists update_seller_configs_updated_at on seller_configs;
create trigger update_seller_configs_updated_at before update on seller_configs
for each row execute function update_updated_at_column();

drop trigger if exists update_listings_updated_at on listings;
create trigger update_listings_updated_at before update on listings
for each row execute function update_updated_at_column();

drop trigger if exists update_claims_updated_at on claims;
create trigger update_claims_updated_at before update on claims
for each row execute function update_updated_at_column();
