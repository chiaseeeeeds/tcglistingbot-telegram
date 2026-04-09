insert into cards (game, set_code, set_name, card_number, card_name_en, card_name_jp, variant, rarity)
values
    ('pokemon', 'sv8a', 'Terastal Festival', '013', 'Palafin', 'イルカマン', 'SAR', 'Special Art Rare'),
    ('pokemon', 'sv8a', 'Terastal Festival', '017', 'Espeon', 'エーフィ', 'Master Ball', 'Special Art Rare'),
    ('onepiece', 'OP09', 'Emperors in the New World', '051', 'Monkey.D.Luffy', 'モンキー・D・ルフィ', 'SR', 'Super Rare'),
    ('onepiece', 'EB01', 'Memorial Collection', '061', 'Tony Tony.Chopper', 'トニートニー・チョッパー', 'SEC', 'Secret Rare')
on conflict do nothing;
