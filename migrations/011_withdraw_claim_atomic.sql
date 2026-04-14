alter table claims
    add column if not exists withdrawn_at timestamptz;

create or replace function withdraw_claim_atomic(
    p_claim_id uuid,
    p_buyer_telegram_id bigint,
    p_next_payment_deadline timestamptz
)
returns jsonb
language plpgsql
as $$
declare
    locked_claim claims;
    locked_listing listings;
    withdrawn_claim claims;
    next_fixed_claim claims;
    promoted_claim claims;
    next_bid_claim claims;
    remaining_open_count integer := 0;
begin
    select * into locked_claim
    from claims
    where id = p_claim_id
    for update;

    if locked_claim.id is null then
        return jsonb_build_object('action', 'noop', 'reason', 'claim_not_found');
    end if;

    if locked_claim.buyer_telegram_id <> p_buyer_telegram_id then
        return jsonb_build_object(
            'action', 'noop',
            'reason', 'buyer_mismatch',
            'claim', to_jsonb(locked_claim)
        );
    end if;

    if locked_claim.status not in ('queued', 'confirmed', 'payment_pending') then
        return jsonb_build_object(
            'action', 'noop',
            'reason', 'claim_not_withdrawable',
            'claim', to_jsonb(locked_claim)
        );
    end if;

    select * into locked_listing
    from listings
    where id = locked_claim.listing_id
    for update;

    if locked_listing.id is null then
        return jsonb_build_object(
            'action', 'noop',
            'reason', 'listing_not_found',
            'claim', to_jsonb(locked_claim)
        );
    end if;

    update claims
    set status = 'withdrawn',
        withdrawn_at = now(),
        updated_at = now()
    where id = locked_claim.id
    returning * into withdrawn_claim;

    if locked_claim.status = 'queued' then
        update claims
        set queue_position = greatest(queue_position - 1, 1),
            updated_at = now()
        where listing_id = locked_claim.listing_id
          and status = 'queued'
          and queue_position > coalesce(locked_claim.queue_position, 1);

        select count(*) into remaining_open_count
        from claims
        where listing_id = locked_claim.listing_id
          and status in ('queued', 'confirmed', 'payment_pending');

        if remaining_open_count = 0 then
            update listings
            set status = case when locked_listing.listing_type = 'auction' then 'auction_closed' else 'active' end,
                updated_at = now()
            where id = locked_claim.listing_id
            returning * into locked_listing;

            return jsonb_build_object(
                'action', 'reactivated',
                'listing', to_jsonb(locked_listing),
                'withdrawn_claim', to_jsonb(withdrawn_claim)
            );
        end if;

        return jsonb_build_object(
            'action', 'withdrawn',
            'listing', to_jsonb(locked_listing),
            'withdrawn_claim', to_jsonb(withdrawn_claim)
        );
    end if;

    if locked_listing.listing_type = 'auction' then
        select * into next_bid_claim
        from claims
        where listing_id = locked_claim.listing_id
          and status = 'bid_active'
        order by bid_amount_sgd desc nulls last, claimed_at asc
        limit 1
        for update;

        if next_bid_claim.id is null then
            update listings
            set status = 'auction_closed',
                updated_at = now()
            where id = locked_claim.listing_id
            returning * into locked_listing;

            return jsonb_build_object(
                'action', 'auction_closed',
                'listing', to_jsonb(locked_listing),
                'withdrawn_claim', to_jsonb(withdrawn_claim)
            );
        end if;

        update claims
        set status = 'confirmed',
            queue_position = 1,
            confirmed_at = now(),
            payment_deadline = p_next_payment_deadline,
            updated_at = now()
        where id = next_bid_claim.id
        returning * into promoted_claim;

        update listings
        set status = 'claim_pending',
            price_sgd = coalesce(promoted_claim.bid_amount_sgd, current_bid_sgd, starting_bid_sgd, price_sgd),
            current_bid_sgd = coalesce(promoted_claim.bid_amount_sgd, current_bid_sgd, starting_bid_sgd),
            updated_at = now()
        where id = locked_claim.listing_id
        returning * into locked_listing;

        return jsonb_build_object(
            'action', 'promoted',
            'listing', to_jsonb(locked_listing),
            'withdrawn_claim', to_jsonb(withdrawn_claim),
            'promoted_claim', to_jsonb(promoted_claim)
        );
    end if;

    select * into next_fixed_claim
    from claims
    where listing_id = locked_claim.listing_id
      and status = 'queued'
    order by queue_position asc, claimed_at asc
    limit 1
    for update;

    if next_fixed_claim.id is null then
        update listings
        set status = 'active',
            updated_at = now()
        where id = locked_claim.listing_id
        returning * into locked_listing;

        return jsonb_build_object(
            'action', 'reactivated',
            'listing', to_jsonb(locked_listing),
            'withdrawn_claim', to_jsonb(withdrawn_claim)
        );
    end if;

    update claims
    set queue_position = greatest(queue_position - 1, 2),
        updated_at = now()
    where listing_id = locked_claim.listing_id
      and status = 'queued'
      and queue_position > coalesce(next_fixed_claim.queue_position, 1);

    update claims
    set status = 'confirmed',
        confirmed_at = now(),
        payment_deadline = p_next_payment_deadline,
        queue_position = 1,
        updated_at = now()
    where id = next_fixed_claim.id
    returning * into promoted_claim;

    update listings
    set status = 'claim_pending',
        updated_at = now()
    where id = locked_claim.listing_id
    returning * into locked_listing;

    return jsonb_build_object(
        'action', 'promoted',
        'listing', to_jsonb(locked_listing),
        'withdrawn_claim', to_jsonb(withdrawn_claim),
        'promoted_claim', to_jsonb(promoted_claim)
    );
end;
$$;
