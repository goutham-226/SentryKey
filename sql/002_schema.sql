CREATE TABLE api_keys(
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    monthly_quota BIGINT DEFAULT 100000,
    revoked_on TIMESTAMPTZ,
    created_on TIMESTAMPTZ NOT NULL DEFAULT now()
);
