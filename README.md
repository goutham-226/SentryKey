<div align="center">

# SentryKey

**A multi-provider AI gateway with metered access, tiered models, and persistent conversation memory.**

A single endpoint for nine top AI models across three providers. It tracks your daily token usage, manages API keys, and seamlessly holds onto your conversation history even when you switch models mid-chat.

[![CI](https://img.shields.io/github/actions/workflow/status/goutham-226/SentryKey/python-app.yml?branch=main&style=flat-square&logo=githubactions&logoColor=white&label=CI)](https://github.com/goutham-226/SentryKey/actions)
[![Python](https://img.shields.io/badge/python-3.14-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Alembic](https://img.shields.io/badge/Alembic-migrations-6BA81E?style=flat-square)](https://alembic.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

[Overview](#overview) &nbsp;&middot;&nbsp;
[Architecture](#architecture) &nbsp;&middot;&nbsp;
[Design](#design) &nbsp;&middot;&nbsp;
[Running it](#running-it) &nbsp;&middot;&nbsp;
[API](#api) &nbsp;&middot;&nbsp;
[Data model](#data-model) &nbsp;&middot;&nbsp;
[Project layout](#project-layout) &nbsp;&middot;&nbsp;
[Known flaws](#known-flaws)

</div>

---

## Overview

Talking to several model providers directly means several SDKs, several billing accounts,
several sets of credentials, and no single answer to "what did this cost and who spent it."

**SentryKey** is the layer that fixes that. It exposes one endpoint, routes to whichever
model the caller asked for, and owns everything that sits between a request and an
inference call: who is asking, whether they are entitled to that model, how much they have
spent today, and what the conversation so far consisted of.

Access is tiered, and enforced at the gateway rather than trusted to the client. Each plan
unlocks its own set of models — a plan reaches the models listed under it and models listed in lower tiers.

| Tier | Provider | Model | Context |
| :--- | :--- | :--- | ---: |
| **Premium** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Sol | 1M+ |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Opus 5 | 1M+ |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.1 Pro | 1M+ |
| **Pro** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Terra | 1M+ |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Sonnet 5 | 1M+ |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.5 Flash | 1M+ |
| **Basic** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Luna | 1M+ |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Haiku 4.5 | 200k |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.5 Flash-Lite | 1M+ |

Every tier gets the same 100,000 token daily budget — the plan buys capability, not volume.
The catalog lives in the database, so adding a model, moving one between tiers or pulling
one during an incident is an `UPDATE` rather than a deploy.

OpenAI models are wired up end-to-end today, streamed directly against the OpenAI SDK with
per-chunk token accounting. Anthropic and Google are catalogued and gated by tier already,
but return `400 provider not available at the moment` until their provider clients land.

Because history lives in the gateway rather than the client, a conversation is portable
across models. Start on one model, continue on another, and the thread comes with you.

## Architecture

```mermaid
flowchart TB
    C[Client]

    subgraph GW["SentryKey"]
        direction TB
        AUTH["Auth<br/>key hash → api_key → user"]
        ENT["Entitlement<br/>subscription tier ≥ model tier"]
        QUOTA["Quota<br/>tokens used in last 24h"]
        CTX["Context<br/>history up to 1000 tokens"]
        PROV["Provider client"]
    end

    OAI["OpenAI"]
    ANT["Anthropic<br/>not wired yet"]
    GEM["Google<br/>not wired yet"]
    METER["Save<br/>messages + usage record"]
    R[Client response]
    PG[("PostgreSQL")]

    C -->|Bearer key| AUTH --> ENT --> QUOTA --> CTX --> PROV
    PROV -->|openai| OAI
    PROV -.->|anthropic| ANT
    PROV -.->|google| GEM
    OAI --> METER -->|JSON| R

    GW -.-> PG
    METER -.-> PG
```

Authentication and entitlement run as a FastAPI dependency before the handler is reached, and the quota check runs before any provider call, so no upstream request is ever made for a caller who isn't allowed one. Every request that reaches a provider writes a usage record, including ones that fail mid-stream, so partially generated tokens are still billed.

## Design

Six constraints shape the implementation. Each rules out the obvious naive approach.

**Raw keys are never stored.** Only a SHA-256 digest and a short display prefix are
persisted. Authentication hashes the presented key and looks up the digest, so the lookup
stays a single indexed query while a database dump stays unusable. A lost key is replaced,
never recovered.

**Keys are revoked, never deleted.** Revoking a key sets `revoked_on` instead of removing
the row. Authentication rejects any key with a revocation date, while its conversations
and usage records — which would otherwise cascade away — stay intact for billing and audit.

**Entitlement is derived, never cached on the user.** A user has no tier column. The active
subscription — a dated row, not a flag — is the only answer to what they may reach, so
expiry is a fact about time rather than a state something must remember to update.

**Spend is a ledger, not a counter.** Every request writes a usage row with real token
counts reported by the provider. Remaining quota is a `SUM` over today's rows, served by a
composite index. Nothing increments a running total, so nothing can drift, and several
replicas agree without coordinating.

**Context is assembled per request, against the model being used now.** Context windows
differ by two orders of magnitude across the catalog, so a conversation is a message log
with no model attached and the truncation budget is recomputed every turn. Switching models
mid-thread is a supported operation rather than a corruption.

**Schema changes go through migrations.** Every table is defined by a reversible Alembic
revision. No table is altered by hand, in any environment.

**Streaming is billed by what actually happened, not by the request.** A provider call can
fail before, during or after tokens were generated, and each of those is billed differently.
Errors raised before the first chunk arrives are free; a stream interrupted mid-generation
still charges for what was produced, plus a fixed buffer, because the provider already did
the work. The response is only ever built from tokens the stream actually returned.

## Running it

**Requirements:** Python 3.14, Docker

```bash
git clone https://github.com/goutham-226/SentryKey.git
cd SentryKey

docker compose up -d
cp .env.example .env          # set DATABASE_URL and the provider token

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head          # schema, plus the subscription tiers
python -m scripts.model_seed  # the model catalog (safe to re-run)

uvicorn app.main:app --reload
```

Interactive documentation is served at **http://127.0.0.1:8000/docs**, generated from the
route signatures and Pydantic models, so it never drifts from the code.

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

### Running the tests

The suite runs against a separate `sk_test` database in the same Postgres container, so
development data is never touched. Migrations and the model catalog are applied once per
run; every test starts from empty user, key and usage tables.

```bash
pip install -r requirements-dev.txt
docker exec -it kq-postgres createdb -U kq sk_test   # first time only

pytest -v
```

The same suite runs in CI on every push and pull request to `main`, against a fresh
Postgres service.

## API

| | Method | Path | Description |
| :---: | :--- | :--- | :--- |
| 🔓 | `GET` | `/health` | Liveness probe. Unversioned — infrastructure, not API surface. |
| 🔓 | `POST` | `/v1/auth/register` | Create an account. `409` on a duplicate email. |
| 🔓 | `GET` | `/v1/models-catalog` | The public catalog: every active model and the plan it needs. |
| 🔑 | `POST` | `/v1/keys` | Issue an API key. The raw value is returned **once**, along with its `key_id`. |
| 🔑 | `GET` | `/v1/keys` | List the caller's active keys by prefix, with `key_id` and quota. Revoked keys are hidden. `404` if the caller has no active keys. |
| 🔑 | `DELETE` | `/v1/keys/{key_id}` | Revoke one of the caller's keys. The row is kept (`revoked_on` is set) so usage history survives, and the key is rejected with `401` from then on. `404` if the key doesn't exist or belongs to someone else. |
| 🔑 | `POST` | `/v1/subscriptions` | Subscribe to Basic, Pro or Premium for one month. `409` if a subscription is already active. |
| 🔐 | `POST` | `/v1/chat/completions` | Run a prompt against a model in the caller's tier, optionally continuing a conversation. `403` without an active subscription or for a model outside the tier, `429` once the daily budget is spent, `400` if the model's provider isn't wired up yet (Anthropic, Google). |
| 🔐 | `GET` | `/v1/chat-history/{conversation_id}` | Full message log for a conversation owned by the caller's key. `404` if the conversation doesn't exist or belongs to a different key. |

🔓 ![Public](https://img.shields.io/badge/auth-public-brightgreen) &nbsp;&middot;&nbsp; 🔑 ![Auth](https://img.shields.io/badge/auth-password-orange) &nbsp;&middot;&nbsp; 🔐 ![API Key](https://img.shields.io/badge/auth-bearer_token-blue)

Two credentials, deliberately. Key management and billing require the account password,
because an API key is a bearer credential that lives in config files and CI variables — a
leaked key can spend quota, but it cannot mint more keys, change the plan or escalate. The
same rule is what makes revocation work: the owner revokes a leaked or lost key with the
password, without ever needing the key itself.

### Getting from zero to a completion

**1. Issue a key.**

```bash
curl -X POST http://127.0.0.1:8000/v1/keys \
  -H 'Content-Type: application/json' \
  -d '{"email": "asha@example.com", "password": "correct-horse-battery"}'
```

```json
{
  "api_key": "kq_z9_Nuql9B9YsDYmhBfWPvBLvlCeXzIU",
  "daily_quota": 100000,
  "key_id": 1
}
```

That value is shown once and cannot be retrieved. Only its first eleven characters and a
hash are stored. Keep the `key_id` — it is how the key is revoked later.

**2. Subscribe to a plan.** The period starts now and runs for one month; the database
computes both ends.

```bash
curl -X POST http://127.0.0.1:8000/v1/subscriptions \
  -u 'asha@example.com:correct-horse-battery' \
  -H 'Content-Type: application/json' \
  -d '{"tier": "Basic"}'
```

**3. Send a prompt.** Omit `conversation_id` to start a new conversation; send back the
returned id to continue it, on the same model or a different one.

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H 'Authorization: Bearer kq_z9_Nuql9B9YsDYmhBfWPvBLvlCeXzIU' \
  -H 'Content-Type: application/json' \
  -d '{
        "model": "gpt-5.6-luna",
        "prompt": "Explain the computer programs written for the Apollo moon landing",
        "max_tokens": 512
      }'
```

```json
{
  "model": "gpt-5.6-luna",
  "output": "The Apollo Guidance Computer ran software written in...",
  "prompt_tokens": 16,
  "completion_tokens": 498,
  "quota_remaining": 99486,
  "conversation_id": 1
}
```

`max_tokens` is clamped to the remaining daily budget before the request reaches the
provider, so a single call cannot overrun the quota by more than its own prompt.

**4. Pull the conversation back.**

```bash
curl http://127.0.0.1:8000/v1/chat-history/1 \
  -H 'Authorization: Bearer kq_z9_Nuql9B9YsDYmhBfWPvBLvlCeXzIU'
```

```json
[
  {
    "conversation_id": 1,
    "role": "user",
    "message": "Explain the computer programs written for the Apollo moon landing",
    "model": "gpt-5.6-luna",
    "timestamp": "2026-09-22T17:22:31.016184Z"
  },
  {
    "conversation_id": 1,
    "role": "assistant",
    "message": "The Apollo Guidance Computer ran software written in...",
    "model": "gpt-5.6-luna",
    "timestamp": "2026-09-22T17:22:33.512009Z"
  }
]
```

Scoped to the bearer key that owns the conversation — a `404` either way if it doesn't
exist or belongs to someone else, so the endpoint never confirms another key's conversation
ids exist.

**5. Switch models mid-conversation.** Send the same `conversation_id` with a different
`model`. The conversation carries on, and the new model receives the earlier turns as context.

Entitlement is checked on every request against the model named in that request, not the one
the conversation started on. Asha is on Basic, so moving up to `gpt-5.6-terra` is refused:

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H 'Authorization: Bearer kq_z9_Nuql9B9YsDYmhBfWPvBLvlCeXzIU' \
  -H 'Content-Type: application/json' \
  -d '{
        "model": "gpt-5.6-terra",
        "prompt": "Which language was that software written in?",
        "max_tokens": 512,
        "conversation_id": 1
      }'
```

```json
{
  "detail": "user lacks privilege"
}
```

| Tier    | GPT models available                           |
|---------|------------------------------------------------|
| Basic   | `gpt-5.6-luna`                                 |
| Pro     | `gpt-5.6-luna`, `gpt-5.6-terra`                |
| Premium | `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol` |

On a Pro subscription, the same request goes through and the reply is added to conversation `1`:

```json
{
  "model": "gpt-5.6-terra",
  "output": "The AGC software was written in an assembly language...",
  "prompt_tokens": 531,
  "completion_tokens": 402,
  "quota_remaining": 98553,
  "conversation_id": 1
}
```

How the history is carried over:

- The gateway loads the conversation's messages newest first. It keeps as many as fit in the
  context budget: 1,000 tokens per request, or less if the key's remaining daily context quota
  is lower. The message that crosses the limit is trimmed rather than dropped. The kept messages
  are then sent oldest to newest, followed by the new prompt.
- Messages are sent as plain `role` + `content`, and the model that produced each one isn't
  passed along. The new model sees the earlier assistant turns as if it had written them itself.
- The history counts toward `prompt_tokens`, which is why that figure jumps from 16 to 531.
  So continuing a conversation costs more of the daily token quota than starting a new one.
  The history tokens also count against the key's separate daily context quota.
- Every message stores the model that produced it, so `/v1/chat-history/1` shows where the
  switch happened:

```json
[
  { "conversation_id": 1, "role": "user",      "message": "Explain the computer programs...", "model": "gpt-5.6-luna",  "timestamp": "..." },
  { "conversation_id": 1, "role": "assistant", "message": "The Apollo Guidance Computer...",  "model": "gpt-5.6-luna",  "timestamp": "..." },
  { "conversation_id": 1, "role": "user",      "message": "Which language was that...",      "model": "gpt-5.6-terra", "timestamp": "..." },
  { "conversation_id": 1, "role": "assistant", "message": "The AGC software was written...", "model": "gpt-5.6-terra", "timestamp": "..." }
]
```

**6. Revoke a key.** Use the `key_id` from step 1, or look it up with `GET /v1/keys`.

```bash
curl -X DELETE http://127.0.0.1:8000/v1/keys/1 \
  -u 'asha@example.com:correct-horse-battery'
```

```json
{ "status": "success" }
```

From here on, any request made with that key is rejected with `401`, and it no longer
appears in `GET /v1/keys`. Its conversations and usage records are kept.

## Data model

```
subscription_tiers ──< users ──< api_keys ──< conversations ──< messages
        │                             │              │
        └──< subscriptions            └──< usage_records >──┘
                                                │
                             models ────────────┘
```

Eight tables. `subscription_tiers` and `models` are catalog data — a model launch, a price
change or an emergency deactivation is an `UPDATE`, never a deploy. `subscriptions` records
what a user bought and for how long, and is the sole source of truth for entitlement.
`usage_records` is the ledger every quota decision and every cost report derives from.

Cascades differ per relationship, deliberately: keys and conversations cascade from their
owner, usage records keep their row when a conversation is deleted, and a retired model
never rewrites history. API keys are revoked with a timestamp rather than deleted, so the
cascade from a key never fires in normal use.

## Project layout

```
.
├── .github/workflows/
│   └── python-app.yml           CI — flake8 + pytest against a Postgres service on every push/PR to main
├── app/
│   ├── main.py                  Routes
│   ├── config.py                Settings from the environment
│   ├── db.py                    Async engine, session factory, get_db
│   ├── deps.py                  Auth dependencies — password and API key
│   ├── security.py              Password hashing
│   ├── models.py                SQLAlchemy ORM — the database schema
│   ├── schemas.py               Pydantic — the API contract
│   └── services/
│       └── provider.py          Per-provider inference calls, context budgeting, billing-safe streaming
├── tests/
│   ├── __init__.py              Marks tests as a package
│   ├── conftest.py              Fixtures — test DB override, migrations + model seeding, per-test cleanup, async client, user / key / subscription fixtures
│   ├── test_health.py           Smoke test for GET /health
│   ├── test_auth.py             POST /v1/auth/register
│   ├── test_keys.py             POST, GET and DELETE /v1/keys — issuing, listing and revoking keys
│   ├── test_subscriptions.py    POST /v1/subscriptions
│   ├── test_security.py         Unit tests for password hashing
│   └── test_schemas.py          Unit tests for Pydantic request/response validation
├── alembic/versions/            One reversible revision per schema change
├── scripts/                     Catalog seeding (idempotent — safe to re-run)
├── sql/                         The original hand-written schema and reporting queries
├── docs/                        Dev notes on provider SDKs and error-handling design
├── .pre-commit-config.yaml      Local hooks — YAML check, large files, ruff, pytest on pre-push
├── docker-compose.yaml          PostgreSQL 17, named volume, health check
├── pytest.ini                   Pytest config — async mode, test paths
├── requirements.txt             Runtime dependencies
└── requirements-dev.txt         Runtime + test dependencies (pytest, pytest-asyncio, pytest-cov)
```

Input and output schemas are kept separate throughout. A client cannot set a server-owned
field, because no such field exists on the input model; a secret cannot leak, because the
response model does not declare it. Both hold by construction rather than by review.

## Known flaws

### Race condition on concurrent requests (read-modify-write)

When two requests from the same user or API key arrive at nearly the same time, both read the current value from the database (for example, remaining quota or usage) before either one writes its update. Each request sees the same unmodified value, passes the same check, and writes its result based on that stale read.

**Example:**

1. Request A reads `remaining = 1`
2. Request B reads `remaining = 1`, before A has written anything
3. Both pass the `remaining > 0` check and call the provider
4. Both write `remaining = 0`

Result: two requests were served against one unit of quota. One decrement was lost (a *lost update*), so the recorded usage is lower than the real usage.

**Why it happens:** the check and the update are two separate statements inside a transaction running at PostgreSQL's default `READ COMMITTED` isolation level. That level does not stop another transaction from reading the same row between those two statements.

**Impact:** a client that fires parallel requests can go over its quota, and usage or billing records can undercount. The risk increases with concurrency.

**Possible fixes (not yet implemented):**
- **Row lock:** `SELECT ... FOR UPDATE` on the row being checked, so concurrent requests queue up behind each other
- **Atomic conditional update:** do the check and the write in one statement, for example `UPDATE ... SET remaining = remaining - 1 WHERE id = :id AND remaining > 0 RETURNING remaining`. If zero rows come back, the request is rejected.
- **Stricter isolation:** run the transaction at `SERIALIZABLE` and retry on serialization failures
- **Atomic counter outside Postgres:** use a Redis `INCR`/`DECR` for the fast-path quota check, and reconcile with Postgres afterward

**Test gap:** the current suite runs requests one at a time, so this bug is never exercised. A regression test would fire N concurrent requests with `asyncio.gather` against a key with a quota below N, then assert that no more than the quota succeeded.

## License

MIT — see [LICENSE](LICENSE).
