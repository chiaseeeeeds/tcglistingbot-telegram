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
    active_claim claims;
    existing_buyer_claim claims;
    inserted_claim claims;
    next_queue_position integer;
begin
    select * into locked_listing
    from listings
    where id = p_listing_id and status in ('active', 'claim_pending')
    for update;

    if locked_listing.id is null then
        raise exception 'Listing is not claimable';
    end if;

    select * into existing_buyer_claim
    from claims
    where listing_id = p_listing_id
      and buyer_telegram_id = p_buyer_telegram_id
      and status in ('queued', 'confirmed', 'payment_pending')
    order by queue_position asc, created_at asc
    limit 1;

    if existing_buyer_claim.id is not null then
        return existing_buyer_claim;
    end if;

    select * into active_claim
    from claims
    where listing_id = p_listing_id
      and status in ('confirmed', 'payment_pending')
    order by queue_position asc, created_at asc
    limit 1;

    select coalesce(max(queue_position), 0) + 1 into next_queue_position
    from claims
    where listing_id = p_listing_id
      and status in ('queued', 'confirmed', 'payment_pending');

    if active_claim.id is null then
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
        'queued',
        next_queue_position,
        now(),
        null,
        null
    )
    returning * into inserted_claim;

    update listings
    set status = 'claim_pending'
    where id = p_listing_id;

    return inserted_claim;
end;
$$;
