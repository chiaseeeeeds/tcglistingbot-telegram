alter table sellers enable row level security;
alter table seller_configs enable row level security;
alter table cards enable row level security;
alter table listings enable row level security;
alter table listing_channels enable row level security;
alter table claims enable row level security;
alter table transactions enable row level security;
alter table strikes enable row level security;
alter table seller_buyer_blacklist enable row level security;
alter table scheduled_listings enable row level security;

drop policy if exists cards_public_read on cards;
create policy cards_public_read on cards for select using (true);
