alter table if exists listings
    add column if not exists reserve_price_sgd numeric(8, 2),
    add column if not exists auction_payment_deadline_hours integer;


create or replace function close_auction_atomic(
    p_listing_id uuid,
    p_payment_deadline timestamptz,
    p_force boolean default false
)
returns jsonb
language plpgsql
as $$
declare
    locked_listing listings;
    winning_bid claims;
    awarded_claim claims;
    reserve_price numeric(8, 2);
    winning_amount numeric(8, 2);
begin
    select * into locked_listing
    from listings
    where id = p_listing_id
      and listing_type = 'auction'
    for update;

    if locked_listing.id is null then
        return jsonb_build_object('action', 'noop', 'reason', 'listing_not_found');
    end if;

    if locked_listing.status <> 'auction_active' then
        return jsonb_build_object(
            'action', 'noop',
            'reason', 'listing_not_active',
            'listing', to_jsonb(locked_listing)
        );
    end if;

    if not p_force and locked_listing.auction_end_time is not null and locked_listing.auction_end_time > now() then
        return jsonb_build_object(
            'action', 'noop',
            'reason', 'auction_not_due',
            'listing', to_jsonb(locked_listing)
        );
    end if;

    select * into winning_bid
    from claims
    where listing_id = p_listing_id
      and status = 'bid_active'
    order by bid_amount_sgd desc nulls last, claimed_at asc
    limit 1
    for update;

    if winning_bid.id is null then
        update listings
        set status = 'auction_closed',
            updated_at = now()
        where id = p_listing_id
        returning * into locked_listing;

        return jsonb_build_object(
            'action', 'closed_without_bids',
            'listing', to_jsonb(locked_listing)
        );
    end if;

    reserve_price := locked_listing.reserve_price_sgd;
    winning_amount := coalesce(winning_bid.bid_amount_sgd, locked_listing.current_bid_sgd, locked_listing.starting_bid_sgd, 0);

    if reserve_price is not null and winning_amount < reserve_price then
        update claims
        set status = 'rejected',
            failed_at = now(),
            updated_at = now()
        where listing_id = p_listing_id
          and status in ('bid_active', 'outbid');

        update listings
        set status = 'auction_closed',
            updated_at = now()
        where id = p_listing_id
        returning * into locked_listing;

        return jsonb_build_object(
            'action', 'reserve_not_met',
            'listing', to_jsonb(locked_listing),
            'highest_bid_claim', to_jsonb(winning_bid)
        );
    end if;

    update claims
    set status = 'confirmed',
        queue_position = 1,
        confirmed_at = now(),
        payment_deadline = p_payment_deadline,
        updated_at = now()
    where id = winning_bid.id
    returning * into awarded_claim;

    update listings
    set status = 'claim_pending',
        price_sgd = coalesce(awarded_claim.bid_amount_sgd, current_bid_sgd, starting_bid_sgd, price_sgd),
        current_bid_sgd = coalesce(awarded_claim.bid_amount_sgd, current_bid_sgd, starting_bid_sgd),
        updated_at = now()
    where id = p_listing_id
    returning * into locked_listing;

    return jsonb_build_object(
        'action', 'awarded',
        'listing', to_jsonb(locked_listing),
        'winning_claim', to_jsonb(awarded_claim)
    );
end;
$$;
