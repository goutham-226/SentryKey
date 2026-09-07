SELECT api_key_id, SUM(token_count)
FROM usage_records GROUP BY api_key_id;

