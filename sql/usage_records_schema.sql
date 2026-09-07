CREATE TABLE usage_records(
    id BIGSERIAL PRIMARY KEY,
    api_key_id BIGINT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    token_count BIGINT NOT NULL,
    status_code SMALLINT NOT NULL,
    latency_ms INTEGER  NOT NULL
);
 
