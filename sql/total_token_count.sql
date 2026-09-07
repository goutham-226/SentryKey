SELECT COUNT(*) as request_count, SUM(token_count) as token_count
FROM usage_records WHERE api_key_id=6 AND requested_at > now() - interval '30 days';

