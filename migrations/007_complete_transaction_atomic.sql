create or replace function complete_transaction_atomic(
    p_listing_id uuid,
    p_seller_id uuid
)
returns jsonb
language plpgsql
as $$
declare
    locked_listing listings;
    winning_claim claims;
    paid_claim claims;
    created_transaction transactions;
    existing_transaction transactions;
begin
    select * into locked_listing
    from listings
    where id = p_listing_id
      and seller_id = p_seller_id
    for update;

    if locked_listing.id is null then
        raise exception 'Listing not found for seller';
    end if;

    select * into existing_transaction
    from transactions
    where listing_id = p_listing_id
    order by created_at asc
    limit 1;

    if locked_listing.status = 'sold' and existing_transaction.id is not null then
        return jsonb_build_object(
            'action', 'already_completed',
            'listing', to_jsonb(locked_listing),
            'transaction', to_jsonb(existing_transaction)
        );
    end if;

    if locked_listing.status <> 'claim_pending' then
        raise exception 'Listing is not ready to be completed';
    end if;

    select * into winning_claim
    from claims
    where listing_id = p_listing_id
      and status in ('confirmed', 'payment_pending')
    order by queue_position asc, claimed_at asc
    limit 1
    for update;

    if winning_claim.id is null then
        raise exception 'No active winning claim found';
    end if;

    update claims
    set status = 'paid',
        paid_at = now(),
        updated_at = now()
    where id = winning_claim.id
    returning * into paid_claim;

    insert into transactions (
        listing_id,
        claim_id,
        seller_id,
        buyer_telegram_id,
        buyer_username,
        buyer_display_name,
        final_price_sgd,
        completed_at
    )
    values (
        p_listing_id,
        paid_claim.id,
        p_seller_id,
        paid_claim.buyer_telegram_id,
        paid_claim.buyer_username,
        paid_claim.buyer_display_name,
        coalesce(locked_listing.price_sgd, 0),
        now()
    )
    returning * into created_transaction;

    update listings
    set status = 'sold'
    where id = p_listing_id
    returning * into locked_listing;

    update sellers
    set total_sales_sgd = total_sales_sgd + coalesce(locked_listing.price_sgd, 0),
        updated_at = now()
    where id = p_seller_id;

    return jsonb_build_object(
        'action', 'completed',
        'listing', to_jsonb(locked_listing),
        'paid_claim', to_jsonb(paid_claim),
        'transaction', to_jsonb(created_transaction)
    );
end;
$$;
