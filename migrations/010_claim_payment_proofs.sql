alter table claims
    add column if not exists payment_reference text;

create unique index if not exists idx_claims_payment_reference
    on claims(payment_reference)
    where payment_reference is not null;

create table if not exists claim_payment_proofs (
    id uuid primary key default uuid_generate_v4(),
    claim_id uuid not null references claims(id) on delete cascade,
    listing_id uuid not null references listings(id) on delete cascade,
    seller_id uuid not null references sellers(id) on delete cascade,
    buyer_telegram_id bigint not null,
    payment_reference text not null,
    storage_path text not null,
    telegram_file_id text not null,
    telegram_message_id bigint,
    buyer_caption text,
    status text not null default 'submitted',
    seller_note text,
    reviewed_at timestamptz,
    reviewed_by_telegram_id bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_claim_payment_proofs_claim_id
    on claim_payment_proofs(claim_id, created_at desc);

create index if not exists idx_claim_payment_proofs_buyer_status
    on claim_payment_proofs(buyer_telegram_id, status, created_at desc);

create unique index if not exists idx_claim_payment_proofs_one_submitted_per_claim
    on claim_payment_proofs(claim_id)
    where status = 'submitted';
