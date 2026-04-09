create or replace function claim_listing_atomic(
    p_listing_id uuid,
    p_buyer_telegram_id bigint,
    p_buyer_username text,
    p_buyer_display_name text,
    p_payment_deadline timestamptz
)
returns claims
language plpgsql
as $$
declare
    locked_listing listings;
    inserted_claim claims;
begin
    select * into locked_listing
    from listings
    where id = p_listing_id and status = 'active'
    for update;

    if locked_listing.id is null then
        raise exception 'Listing is not claimable';
    end if;

    insert into claims (
        listing_id,
        buyer_telegram_id,
        buyer_username,
        buyer_display_name,
        status,
        queue_position,
        claimed_at,
        confirmed_at,
        payment_deadline
    )
    values (
        p_listing_id,
        p_buyer_telegram_id,
        p_buyer_username,
        p_buyer_display_name,
        'confirmed',
        1,
        now(),
        now(),
        p_payment_deadline
    )
    returning * into inserted_claim;

    update listings
    set status = 'claim_pending'
    where id = p_listing_id;

    return inserted_claim;
end;
$$;
