INSERT INTO api_keys (user_id,key_prefix,key_hash,monthly_quota)
VALUES ((SELECT id FROM users WHERE email = 'goutham@gmail.com'),'kqa1b2','fakehash_001',100000),
((SELECT id FROM users WHERE email = 'goutham@gmail.com'),'kqc3d4','fakehash_002',50000),
((SELECT id FROM users WHERE email = 'Akash@gmail.com'),'kqa1b2','fakehash_003',100000);

