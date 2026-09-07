SELECT k.id,u.name,k.key_prefix,k.key_hash FROM api_keys k
JOIN users u on u.id = k.user_id WHERE k.revoked_on is NULL
ORDER BY u.name;

