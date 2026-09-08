SELECT k.id,u.name,k.key_prefix,k.key_hash FROM api_keys k
JOIN users u on u.id = k.user_id WHERE k.revoked_on is NULL
ORDER BY u.name;

SELECT api_key_id, SUM(token_count)
FROM usage_records GROUP BY api_key_id;

SELECT COUNT(*) as request_count, SUM(token_count) as token_count
FROM usage_records WHERE api_key_id=6 AND requested_at > now() - interval '30 days';
