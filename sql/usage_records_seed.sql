INSERT INTO usage_records (api_key_id,requested_at,token_count,status_code,latency_ms)
VALUES
--current month
((SELECT id FROM api_keys WHERE key_hash='fakehash_002'),now(),10000,429,3),
((SELECT id FROM api_keys WHERE key_hash='fakehash_001'),now(),500,200,300),
((SELECT id FROM api_keys WHERE key_hash='fakehash_003'),now(),1000,200,600),
((SELECT id FROM api_keys WHERE key_hash='fakehash_002'),now() - interval '2 days',50000,200,8000),
((SELECT id FROM api_keys WHERE key_hash='fakehash_003'),now() - interval '2 days',400,200,250),
((SELECT id FROM api_keys WHERE key_hash='fakehash_001'),now() - interval '3 days',2000,200,500),
((SELECT id FROM api_keys WHERE key_hash='fakehash_003'),now() - interval '3 days',1500,200,400),
--previous month
((SELECT id FROM api_keys WHERE key_hash='fakehash_001'),now() - interval '40 days',4000,200,850),
((SELECT id FROM api_keys WHERE key_hash='fakehash_003'),now() - interval '40 days',3500,200,825),
((SELECT id FROM api_keys WHERE key_hash='fakehash_001'),now() - interval '41 days',4500,200,875),
((SELECT id FROM api_keys WHERE key_hash='fakehash_003'),now() - interval '41 days',5000,200,900),
((SELECT id FROM api_keys WHERE key_hash='fakehash_001'),now() - interval '42 days',1500,200,400),
((SELECT id FROM api_keys WHERE key_hash='fakehash_003'),now() - interval '42 days',6000,200,1000);

