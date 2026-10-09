<div align="center">

# SentryKey

**A multi-provider AI gateway with metered access, tiered models, and persistent conversation memory.**

A single endpoint for nine top AI models across three providers. It tracks your daily token usage, manages API keys, and seamlessly holds onto your conversation history even when you switch models mid-chat.

[![CI](https://img.shields.io/github/actions/workflow/status/goutham-226/SentryKey/python-app.yml?branch=main&style=flat-square&logo=githubactions&logoColor=white&label=CI)](https://github.com/goutham-226/SentryKey/actions)
[![Python](https://img.shields.io/badge/python-3.14-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
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
[Roadmap](#roadmap-long-term-memory) &nbsp;&middot;&nbsp;
[Known flaws](#known-flaws)

</div>

---

## Overview

Talking to several model providers directly means several SDKs, several billing accounts,
several sets of credentials, and no single answer to "what did this cost and who spent it."

**SentryKey** is the layer that fixes that. It exposes one endpoint, routes to whichever
model the caller asked for, and owns everything that sits between a request and an
inference call: who is asking, whether they are entitled to that model, how much they have
spent in the last 24 hours, and what the conversation so far consisted of.

Access is tiered, and enforced at the gateway rather than trusted to the client. Each plan
unlocks its own set of models — a plan reaches the models listed under it and models listed in lower tiers.

| Tier | Provider | Model | Context |
| :--- | :--- | :--- | ---: |
| **Premium** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Sol | 1M+ |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Opus 5 | 1M+ |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.1 Pro | 1M+ |
| **Pro** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Terra | 200k |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Sonnet 5 | 1M+ |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.5 Flash | 1M+ |
| **Basic** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Luna | 1M+ |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Haiku 4.5 | 200k |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.5 Flash-Lite | 1M+ |

Every API key gets the same budget whatever the plan: 100,000 tokens per rolling 24 hours,
plus a separate 100,000-token daily allowance for conversation history. The plan buys
capability, not volume. The catalog lives in the database, so adding a model, moving one
between tiers or pulling one during an incident is an `UPDATE` rather than a deploy.

OpenAI models are wired up end-to-end today, streamed directly against the OpenAI SDK with
per-chunk token accounting. Anthropic and Google are catalogued and gated by tier already,
but return `404 Model not available at the moment.` until their provider clients land.

Because history lives in the gateway rather than the client, a conversation is portable
across models. Start on one model, continue on another, and the thread comes with you. Each
request carries a **short-term memory** of the conversation's last four exchanges (four user
messages and four assistant replies). A **long-term memory** that uses vector search to pull
relevant details from older turns is [planned](#roadmap-long-term-memory).

## Architecture

```mermaid
flowchart TB
    C[Client]

    subgraph GW["SentryKey"]
        direction TB
        AUTH["Auth<br/>key hash → api_key → user"]
        ENT["Entitlement<br/>subscription tier ≥ model tier"]
        OWN["Ownership<br/>conversation_id belongs to key"]
        QUOTA["Reserve<br/>lock key row → SUM last 24h → insert reservation"]
        CTX["Short-term memory<br/>last 8 messages within context quota"]
        PROV["Provider client"]
        SETTLE["Settle<br/>reservation → real usage + messages"]
        REL["Release<br/>reservation → 0 tokens"]
    end

    OAI["OpenAI"]
    ANT["Anthropic<br/>not wired yet"]
    GEM["Google<br/>not wired yet"]
    R[Client response]
    PG[("PostgreSQL")]

    C -->|Bearer key| AUTH --> ENT --> OWN --> QUOTA --> CTX --> PROV
    PROV -->|openai| OAI
    PROV -.->|anthropic| ANT
    PROV -.->|google| GEM
    OAI --> SETTLE -->|JSON| R
    PROV -.->|exception / cancellation| REL

    GW -.-> PG
```

Authentication and entitlement run as a FastAPI dependency before the handler is reached.
Conversation ownership and the quota reservation run before any provider call, so no
upstream request is ever made for a caller who isn't allowed one. Every request that
reaches a provider settles its usage record, including ones that fail mid-stream, so
partially generated tokens are still billed.

A request uses one database session, but its transaction is committed before the provider
call, which hands the connection back to the pool. A slow or hanging upstream stream
therefore never holds a pooled connection, an open transaction or a row lock. The session
checks a connection out again afterwards to settle the reservation.

## Design

Nine constraints shape the implementation. Each rules out the obvious naive approach.

**Raw keys are never stored.** Only a SHA-256 digest and a short display prefix are
persisted. Authentication hashes the presented key and looks up the digest, so the lookup
stays a single query on a unique column while a database dump stays unusable. A lost key is
replaced, never recovered.

**Keys are revoked, never deleted.** Revoking a key sets `revoked_on` instead of removing
the row. Authentication rejects any key with a revocation date, while its conversations
and usage records — which would otherwise cascade away — stay intact for billing and audit.

**Entitlement is derived, never cached on the user.** A user has no tier column. The active
subscription — a dated row, not a flag — is the only answer to what they may reach, so
expiry is a fact about time rather than a state something must remember to update. Tiers
carry a numeric `rank` (Basic 10, Pro 20, Premium 30), and a request is allowed when the
subscription's rank is at least the model's minimum tier rank.

**Spend is a ledger, not a counter.** Every request writes a usage row with real token
counts reported by the provider. Remaining quota is a `SUM` over the key's rows from the
last 24 hours — a rolling window, not a calendar day. Nothing increments a running total,
so nothing can drift, and several replicas agree without coordinating.

**Quota is reserved before the call, not checked and hoped for.** A plain check-then-write
lets two concurrent requests read the same remaining budget, both pass, and together overrun
it. Admission is therefore a short, serialised reservation:

1. `SELECT ... FOR UPDATE` locks the key's `api_keys` row, so concurrent requests on the
   same key queue here, on every replica, because the lock lives in Postgres.
2. Under the lock, the ledger is summed and the prompt (counted with `tiktoken`) is checked
   against the quota. `max_tokens` is clamped to what's left, and the request gets `429` if
   nothing is.
3. A `Reserved` usage row for `prompt + max_tokens` is inserted and committed, which also
   releases the lock. The next request's `SUM` already includes that reservation.
4. After the provider call, the same row is **settled**: overwritten with the real token
   counts, so any unused budget comes back immediately.
5. If anything raises before settlement, including `asyncio.CancelledError` from a client
   disconnect, the reservation is **released** (set to 0 tokens, status `Failed`) and any
   conversation the request created is deleted. The release runs inside a shielded
   `anyio.CancelScope`, so the cancellation can't interrupt the cleanup itself.

The lock is held only for a few statements, never across the provider stream, so a slow
response on one request doesn't block the next request on that key.

**Context is assembled per request, against the model being used now.** Context windows
differ by an order of magnitude across the catalog, so a conversation is a message log
with no model attached and the history budget is recomputed every turn. Switching models
mid-thread is a supported operation rather than a corruption.

**Short-term memory is the last four exchanges.** Each request carries at most the
conversation's 8 most recent messages (4 user + 4 assistant), walked newest to oldest and
kept whole while they fit the key's remaining daily context quota. The first message that
doesn't fit is dropped along with everything older, and a leading assistant message is
removed so the context always opens with a user turn. History is billed to the separate
context quota, not the main token quota. Older turns are kept in the database but not sent
to the model; bringing the relevant ones back is the job of the planned
[long-term memory](#roadmap-long-term-memory).

**Schema changes go through migrations.** Every table is defined by a reversible Alembic
revision, and the subscription tiers themselves are seeded by one. No table is altered by
hand, in any environment.

**Streaming is billed by what actually happened, not by the request.** A provider call can
fail before, during or after tokens were generated, and each of those is billed differently.
Errors raised before the first chunk arrives are free; a stream interrupted mid-generation
still charges for what was produced, plus a fixed 15-token buffer, because the provider
already did the work. When the stream finishes cleanly, the provider's own usage figures
are recorded; if they never arrive, the gateway falls back to counting the streamed chunks
with `tiktoken`. Every provider returns the same `provider_response` dataclass, so settling
the ledger doesn't depend on which provider served the request. Messages are only saved
once generation has started, so a failed call never adds an empty turn to the
short-term memory.

## Running it

**Requirements:** Python 3.14, Docker

```bash
git clone https://github.com/goutham-226/SentryKey.git
cd SentryKey

docker compose up -d
cp .env.example .env          # set DATABASE_URL, OPENAI_API_KEY and REPLICATE_API_TOKEN

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head          # schema, plus the subscription tiers
python -m scripts.model_seed  # the model catalog (safe to re-run)

uvicorn app.main:app --reload
```

With the bundled Compose file, the database URL is
`postgresql+asyncpg://kq:kq@localhost:5432/kqpostgres`. All three variables are required at
startup — `REPLICATE_API_TOKEN` is only used by the `scripts/provider_test.py` smoke test,
but the settings object refuses to load without it.

Interactive documentation is served at **http://127.0.0.1:8000/docs**, generated from the
route signatures and Pydantic models, so it never drifts from the code.

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

### Running the tests

The suite runs against a separate `sk_test` database in the same Postgres container, so
development data is never touched. Migrations and the model catalog are applied once per
run; every test starts from empty user, key, subscription, conversation, message and usage
tables. Tests never call a real provider.

```bash
pip install -r requirements-dev.txt
docker exec -it kq-postgres createdb -U kq sk_test   # first time only

pytest -v
```

The same suite runs in CI on every push and pull request to `main`, against a fresh
Postgres service, after a flake8 pass that fails the build on syntax errors and undefined
names.

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

Every commit then runs YAML validation, a large-file check, private-key detection,
`ruff check --fix`, and the full pytest suite.

## API

| | Method | Path | Description |
| :---: | :--- | :--- | :--- |
| 🔓 | `GET` | `/health` | Liveness probe. Unversioned — infrastructure, not API surface. |
| 🔓 | `POST` | `/v1/auth/register` | Create an account. Password must be 8–27 characters, name 1–100. `409` on a duplicate email, `422` on invalid input. |
| 🔓 | `GET` | `/v1/models-catalog` | The public catalog: every model's id, provider and the plan it needs. |
| 🔑 | `POST` | `/v1/keys` | Issue an API key. Email and password go in the JSON body. The raw value is returned **once**, along with its `key_id`. `401` on bad credentials. |
| 🔑 | `GET` | `/v1/keys` | List the caller's active keys by prefix, with `key_id` and quota. Revoked keys are hidden. `404` if the caller has no active keys. |
| 🔑 | `DELETE` | `/v1/keys/{key_id}` | Revoke one of the caller's keys. The row is kept (`revoked_on` is set) so usage history survives, and the key is rejected with `401` from then on. `404` if the key doesn't exist or belongs to someone else. |
| 🔑 | `POST` | `/v1/subscriptions` | Subscribe to Basic, Pro or Premium for one month. `409` if a subscription is already active. |
| 🔐 | `POST` | `/v1/chat/completions` | Run a prompt against a model in the caller's tier, optionally continuing a conversation. `403` without an active subscription or for a model outside the tier. `404` for an unknown model, a model whose provider isn't wired up yet (Anthropic, Google), or a `conversation_id` that doesn't exist or belongs to a different key. `422` if `max_tokens` isn't positive. `429` once the daily budget is spent. |
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

```json
{
  "tier": "Basic",
  "period_end": "2026-10-22T17:20:04.118231"
}
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
  "conversation_id": 1,
  "error_detail": null
}
```

`max_tokens` is clamped to the remaining daily budget, under the reservation lock, before
the request reaches the provider. The prompt is counted with `tiktoken` at that point, so
neither a single call nor several concurrent ones can overrun the quota.

The HTTP status is `200` whenever the provider was reached. How the stream ended is
recorded in the usage record's `status` and `status_code`:

| Status | Meaning | Billed |
| :--- | :--- | :--- |
| `Completed` | The stream finished normally. | Real usage reported by the provider |
| `Interrupted` | The stream broke after tokens had started arriving. `output` holds what was generated. | Tokens received + 15-token buffer |
| `Failed` | The provider failed before the first token, or the request raised before settling. `output` is a "model not available" message, and no messages are saved. | Nothing, the reservation is released |

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
  "prompt_tokens": 9,
  "completion_tokens": 402,
  "quota_remaining": 99075,
  "conversation_id": 1,
  "error_detail": null
}
```

How the history is carried over (short-term memory):

- Before anything is reserved, the gateway checks that `conversation_id` belongs to the
  caller's key and returns `404` if it doesn't. Omitting it (or sending `0`) starts a new
  conversation.
- It takes the conversation's **last 8 messages** (4 user + 4 assistant) and walks them newest
  to oldest, keeping whole messages while they fit the key's remaining daily context quota
  (100,000 tokens per rolling 24 hours). The first message that doesn't fit is dropped with
  everything older than it, and a leading assistant message is removed so the history starts
  on a user turn. The kept messages are sent oldest to newest, followed by the new prompt.
- Anything older than those 8 messages is still stored and returned by `/v1/chat-history`,
  but the model doesn't see it. Recalling relevant older details is what the planned
  [long-term memory](#roadmap-long-term-memory) is for.
- Messages are sent as plain `role` + `content`, and the model that produced each one isn't
  passed along. The new model sees the earlier assistant turns as if it had written them itself.
- History is billed to the context quota, not the token quota. The provider's reported prompt
  count includes the history, so the gateway subtracts the history tokens before recording
  `prompt_tokens`. That's why the figure above is only the new prompt, and why continuing a
  conversation costs the same daily token quota as starting one.
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
change or an emergency deactivation is an `UPDATE`, never a deploy. Each model row carries
its provider, minimum tier, context window, the name of the provider's max-tokens parameter,
and input/output prices per million tokens. `subscriptions` records what a user bought and
for how long, and is the sole source of truth for entitlement. `usage_records` is the ledger
every quota decision and every cost report derives from: prompt, completion and context
tokens, plus the upstream status of each call.

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
│   ├── deps.py                  Auth dependencies — password, API key, and API key + tier entitlement
│   ├── security.py              Password hashing (bcrypt)
│   ├── models.py                SQLAlchemy ORM — the database schema
│   ├── schemas.py               Pydantic — the API contract
│   └── services/
│       ├── provider_service.py  get_response orchestration — ownership check, quota reservation (row lock),
│       │                        short-term memory, provider routing, settle / release of the reservation
│       ├── open_ai.py           OpenAI streaming client, tiktoken counting, billable vs non-billable error handling
│       └── provider_data.py     provider_response dataclass — the one result shape every provider returns
├── tests/
│   ├── __init__.py              Marks tests as a package
│   ├── conftest.py              Fixtures — test DB override, migrations + model seeding, per-test cleanup, async client, user / key / subscription fixtures
│   ├── test_health.py           Smoke test for GET /health
│   ├── test_auth.py             POST /v1/auth/register
│   ├── test_keys.py             POST, GET and DELETE /v1/keys — issuing, listing and revoking keys
│   ├── test_subscriptions.py    POST /v1/subscriptions
│   ├── test_catalog.py          GET /v1/models-catalog — every seeded model with its provider and tier
│   ├── test_chat_history.py     GET /v1/chat-history — format, ordering, and 404 for missing or foreign conversations
│   ├── test_deps.py             Auth and entitlement dependencies — missing, unknown and revoked keys, unsubscribed users, tier gating
│   ├── test_security.py         Unit tests for password hashing
│   └── test_schemas.py          Unit tests for Pydantic request/response validation
├── alembic/versions/            One reversible revision per schema change
├── scripts/
│   ├── model_seed.py            Model catalog seeding (idempotent — safe to re-run)
│   └── provider_test.py         Manual smoke test against Replicate
├── sql/                         The original hand-written schema and reporting queries
├── docs/                        Dev notes on provider SDKs and error-handling design
├── .env.example                 Required environment variables
├── .pre-commit-config.yaml      Local hooks — YAML check, large files, private keys, ruff, pytest
├── alembic.ini                  Alembic config
├── docker-compose.yaml          PostgreSQL 17, named volume, health check
├── pytest.ini                   Pytest config — async mode, test paths
├── requirements.txt             Runtime dependencies
└── requirements-dev.txt         Runtime + test dependencies (pytest, pytest-asyncio, pytest-cov)
```

Input and output schemas are kept separate throughout. A client cannot set a server-owned
field, because no such field exists on the input model; a secret cannot leak, because the
response model does not declare it. Both hold by construction rather than by review.

## Roadmap: long-term memory

Short-term memory only covers the last four exchanges. Anything said earlier, like a name,
a constraint set at the start of a long thread, or a decision from yesterday's conversation,
drops out of what the model sees even though it is still in the database. Long-term memory
is meant to bring back the relevant parts of that older history, chosen by what the new
prompt is about. It is **not implemented yet**. The plan:

1. **Embed on write.** When a turn is settled, its messages are embedded and the vectors are
   stored alongside them. Postgres stays the only datastore, with an extension such as
   `pgvector`, so a memory is a row with the same ownership and cascade rules as the
   message it came from.
2. **Search on read.** Before the provider call, the incoming prompt is embedded and a
   nearest-neighbour search runs over the key's older messages: earlier turns of this
   conversation that fall outside the 8-message window, and the key's previous
   conversations. Only results above a similarity threshold are kept.
3. **Merge into context.** The retrieved snippets go ahead of the short-term history, marked
   as recalled context. Short-term memory keeps priority: recalled snippets only use the
   context budget it leaves behind.
4. **Bill it like history.** Recalled tokens count against the daily context quota, and the
   embedding calls are recorded in the ledger, so long-term memory never bypasses the same
   metering every other token goes through.

Every search is filtered by `api_key_id`, matching how `/v1/chat-history` and conversation
continuation are scoped, so one key can never recall another key's messages.

## Known flaws

Fixed in the provider-service refactor: the check-then-act race on concurrent requests (now
a locked reservation), messages being written into another key's conversation (now a `404`
before anything is reserved), and the pre-call prompt estimate using a word count (now
`tiktoken`).

### The context quota isn't reserved

The token quota is checked and reserved under the `api_keys` row lock, but the context
quota is read afterwards, once the lock has been released. Two concurrent requests that
continue conversations can both see the same remaining context budget and together go over it.

**Fix:** compute the trimmed history inside the locked section and write its size into the
reservation row's `context_tokens`, so the next request's `SUM` already sees it.

### A crashed worker leaves its reservation behind

A reservation is released by the request's own exception handler. If the process dies
outright between reserving and settling (`SIGKILL`, OOM, a host failure), that never runs,
and the `Reserved` row keeps counting `prompt + max_tokens` against the key for 24 hours.

**Fix:** a periodic job that releases `Reserved` rows older than the longest possible
provider call.

### Over-reservation near the limit

The full clamped `max_tokens` is reserved up front. While a long request is in flight, a
concurrent request on the same key sees that whole amount as spent, and can be clamped
lower or refused with `429` even though the first request will probably use less. The
budget comes back as soon as the first request settles.

### Empty conversations on failed first turns

A new conversation is committed before the provider call. If that call fails before
generating anything, the request settles normally with nothing billed and no messages saved,
but the empty conversation stays. Conversations are only deleted when the request raises.

### No index on the usage ledger

Every chat request runs two `SUM`s over `usage_records`, one for tokens and one for context,
filtered by `api_key_id` and the last 24 hours. No migration creates an index on
`(api_key_id, requested_at)`, so each check scans more rows as the table grows. The token
`SUM` now runs while the key's row lock is held, so a slow `SUM` also lengthens how long
concurrent requests on that key wait.

**Fix:** add a composite index on `(api_key_id, requested_at)` in a new Alembic revision.
At higher scale, an atomic counter in Redis could take the `SUM` off the hot path entirely,
with the ledger kept as the source of truth.

### `is_active` is not enforced

Models have an `is_active` flag meant for pulling a model during an incident or after a provider deprecates it. Neither `/v1/models-catalog` nor `/v1/chat/completions` checks it, so a deactivated model is still listed and still callable.

**Fix:** filter the catalog on `is_active`, and have the entitlement dependency reject inactive models, for example with `404` or `410 Gone`.


## License

MIT — see [LICENSE](LICENSE).
