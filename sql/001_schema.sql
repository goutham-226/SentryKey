CREATE TABLE users(
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_on TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE api_keys(
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    monthly_quota BIGINT DEFAULT 100000,
    revoked_on TIMESTAMPTZ,
    created_on TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE usage_records(
    id BIGSERIAL PRIMARY KEY,
    api_key_id BIGINT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    token_count BIGINT NOT NULL,
    status_code SMALLINT NOT NULL,
    latency_ms INTEGER  NOT NULL
);
 

