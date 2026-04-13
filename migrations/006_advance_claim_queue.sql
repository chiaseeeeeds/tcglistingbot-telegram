create or replace function advance_claim_queue(
    p_claim_id uuid,
    p_next_payment_deadline timestamptz
)
returns jsonb
language plpgsql
as $$
declare
    locked_claim claims;
    locked_listing listings;
    updated_failed claims;
    next_claim claims;
    promoted_claim claims;
begin
    select * into locked_claim
    from claims
    where id = p_claim_id
    for update;

    if locked_claim.id is null then
        return jsonb_build_object('action', 'noop', 'reason', 'claim_not_found');
    end if;

    if locked_claim.status not in ('confirmed', 'payment_pending') then
        return jsonb_build_object(
            'action', 'noop',
            'reason', 'claim_not_active',
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
    set status = 'failed',
        failed_at = now(),
        updated_at = now()
    where id = locked_claim.id
    returning * into updated_failed;

    select * into next_claim
    from claims
    where listing_id = locked_claim.listing_id
      and status = 'queued'
    order by queue_position asc, claimed_at asc
    limit 1
    for update;

    if next_claim.id is null then
        update listings
        set status = 'active'
        where id = locked_claim.listing_id
        returning * into locked_listing;

        return jsonb_build_object(
            'action', 'reactivated',
            'listing_id', locked_claim.listing_id,
            'listing_status', locked_listing.status,
            'failed_claim', to_jsonb(updated_failed)
        );
    end if;

    update claims
    set status = 'confirmed',
        confirmed_at = now(),
        payment_deadline = p_next_payment_deadline,
        updated_at = now()
    where id = next_claim.id
    returning * into promoted_claim;

    update listings
    set status = 'claim_pending'
    where id = locked_claim.listing_id
    returning * into locked_listing;

    return jsonb_build_object(
        'action', 'promoted',
        'listing_id', locked_claim.listing_id,
        'listing_status', locked_listing.status,
        'failed_claim', to_jsonb(updated_failed),
        'promoted_claim', to_jsonb(promoted_claim)
    );
end;
$$;
