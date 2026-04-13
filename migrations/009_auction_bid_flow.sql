create index if not exists idx_claims_auction_high_bid
    on claims(listing_id, status, bid_amount_sgd desc, claimed_at asc)
    where status in ('bid_active', 'outbid');


create or replace function record_auction_bid_atomic(
    p_listing_id uuid,
    p_buyer_telegram_id bigint,
    p_buyer_username text,
    p_buyer_display_name text,
    p_bid_amount_sgd numeric(8, 2)
)
returns jsonb
language plpgsql
as $$
declare
    locked_listing listings;
    current_high_claim claims;
    buyer_existing_bid claims;
    updated_bid claims;
    previous_high_claim claims;
    minimum_bid numeric(8, 2);
    effective_end_time timestamptz;
    anti_snipe_window interval;
    anti_snipe_extension_applied boolean := false;
begin
    select * into locked_listing
    from listings
    where id = p_listing_id
      and listing_type = 'auction'
    for update;

    if locked_listing.id is null then
        return jsonb_build_object('action', 'rejected', 'reason', 'listing_not_found');
    end if;

    if locked_listing.status <> 'auction_active' then
        return jsonb_build_object(
            'action', 'rejected',
            'reason', 'listing_not_active',
            'listing', to_jsonb(locked_listing)
        );
    end if;

    if locked_listing.auction_end_time is null then
        return jsonb_build_object(
            'action', 'rejected',
            'reason', 'auction_end_missing',
            'listing', to_jsonb(locked_listing)
        );
    end if;

    if locked_listing.auction_end_time <= now() then
        return jsonb_build_object(
            'action', 'rejected',
            'reason', 'auction_ended',
            'listing', to_jsonb(locked_listing)
        );
    end if;

    if p_bid_amount_sgd is null or p_bid_amount_sgd <= 0 then
        return jsonb_build_object('action', 'rejected', 'reason', 'invalid_bid_amount');
    end if;

    select * into current_high_claim
    from claims
    where listing_id = p_listing_id
      and status = 'bid_active'
    order by bid_amount_sgd desc nulls last, claimed_at asc
    limit 1
    for update;

    if current_high_claim.id is null then
        minimum_bid := coalesce(locked_listing.starting_bid_sgd, 0);
    else
        minimum_bid := coalesce(current_high_claim.bid_amount_sgd, locked_listing.current_bid_sgd, locked_listing.starting_bid_sgd, 0)
            + coalesce(locked_listing.bid_increment_sgd, 0.50);
    end if;

    if p_bid_amount_sgd < minimum_bid then
        return jsonb_build_object(
            'action', 'rejected',
            'reason', 'bid_too_low',
            'minimum_bid', minimum_bid,
            'listing', to_jsonb(locked_listing),
            'current_high_claim', case when current_high_claim.id is not null then to_jsonb(current_high_claim) else null end
        );
    end if;

    select * into buyer_existing_bid
    from claims
    where listing_id = p_listing_id
      and buyer_telegram_id = p_buyer_telegram_id
      and status in ('bid_active', 'outbid')
    order by bid_amount_sgd desc nulls last, claimed_at desc
    limit 1
    for update;

    if current_high_claim.id is not null and current_high_claim.buyer_telegram_id <> p_buyer_telegram_id then
        update claims
        set status = 'outbid',
            updated_at = now()
        where id = current_high_claim.id
        returning * into previous_high_claim;
    elsif current_high_claim.id is not null then
        previous_high_claim := current_high_claim;
    end if;

    if buyer_existing_bid.id is null then
        insert into claims (
            listing_id,
            buyer_telegram_id,
            buyer_username,
            buyer_display_name,
            status,
            queue_position,
            bid_amount_sgd,
            claimed_at
        )
        values (
            p_listing_id,
            p_buyer_telegram_id,
            p_buyer_username,
            p_buyer_display_name,
            'bid_active',
            1,
            p_bid_amount_sgd,
            now()
        )
        returning * into updated_bid;
    else
        update claims
        set buyer_username = p_buyer_username,
            buyer_display_name = p_buyer_display_name,
            status = 'bid_active',
            queue_position = 1,
            bid_amount_sgd = p_bid_amount_sgd,
            claimed_at = now(),
            failed_at = null,
            updated_at = now()
        where id = buyer_existing_bid.id
        returning * into updated_bid;
    end if;

    effective_end_time := locked_listing.auction_end_time;
    anti_snipe_window := make_interval(mins => greatest(coalesce(locked_listing.anti_snipe_minutes, 0), 0));
    if anti_snipe_window > interval '0 minutes' and effective_end_time <= now() + anti_snipe_window then
        effective_end_time := greatest(effective_end_time, now()) + anti_snipe_window;
        anti_snipe_extension_applied := true;
    end if;

    update listings
    set current_bid_sgd = p_bid_amount_sgd,
        auction_end_time = effective_end_time,
        updated_at = now()
    where id = p_listing_id
    returning * into locked_listing;

    return jsonb_build_object(
        'action', 'accepted',
        'minimum_bid', minimum_bid,
        'listing', to_jsonb(locked_listing),
        'winning_bid_claim', to_jsonb(updated_bid),
        'previous_high_claim',
            case
                when previous_high_claim.id is not null and previous_high_claim.id <> updated_bid.id then to_jsonb(previous_high_claim)
                else null
            end,
        'anti_snipe_applied', anti_snipe_extension_applied
    );
end;
$$;


create or replace function close_auction_atomic(
    p_listing_id uuid,
    p_payment_deadline timestamptz
)
returns jsonb
language plpgsql
as $$
declare
    locked_listing listings;
    winning_bid claims;
    awarded_claim claims;
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

    if locked_listing.auction_end_time is not null and locked_listing.auction_end_time > now() then
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
