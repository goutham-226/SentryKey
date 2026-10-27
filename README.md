<div align="center">

# SentryKey

**A multi-provider AI gateway with metered access, tiered models, and persistent conversation memory.**

One endpoint for nine AI models from three providers. It tracks daily token usage, manages API keys, and keeps your conversation history even when you switch models mid-chat.

> **At a glance**
>
> - **One API, three providers:** OpenAI, Anthropic and Google, all streamed and all live.
> - **Plans gate models:** Basic, Pro and Premium. The gateway enforces it, not the client.
> - **Metered:** 100,000 tokens per key per rolling 24 hours, tracked in a ledger.
> - **Safe by design:** keys are stored hashed, quota is reserved before every call, and failed calls aren't billed.
> - **Portable chats:** start on GPT, continue on Claude or Gemini.


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



> Authored by [Goutham](https://github.com/goutham-226).
> Core system architecture and execution were completed manually,
> with AI tools limited strictly to reference learning and routine
> code completion.

</div>

---

## Overview

Using several AI providers directly means juggling several SDKs, API keys and bills. It also
leaves no single place to see who spent what.

**SentryKey** puts one endpoint in front of all of them. It checks who is calling, whether
their plan covers the model, and how much they've used today. Then it forwards the request
and remembers the conversation.

Each plan unlocks the models in its own tier and every tier below it. The gateway enforces
this, not the client.

| Tier | Provider | Model | Context |
| :--- | :--- | :--- | ---: |
| **Premium** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Sol | 1M+ |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Opus 5 | 1M+ |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.1 Pro (via Replicate) | 1M+ |
| **Pro** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Terra | 200k |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Sonnet 5 | 1M+ |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.5 Flash | 1M+ |
| **Basic** | [![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)](https://openai.com/) | GPT-5.6 Luna | 1M+ |
| | [![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)](https://www.anthropic.com/) | Claude Haiku 4.5 | 200k |
| | [![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=googlegemini&logoColor=white)](https://gemini.google/in/about/?hl=en-IN) | Gemini 3.5 Flash-Lite | 1M+ |

**Quotas.** Every API key gets 100,000 tokens per rolling 24 hours, whatever the plan. A
separate 100,000-token allowance covers conversation history. Plans buy access to better
models, not more volume.

**Catalog in the database.** Adding a model or moving it between tiers is a
database `UPDATE`, not a redeploy.

**Provider status.** All three providers work end to end and stream through their own SDKs.
Gemini 3.1 Pro is the one exception: it is served through [Replicate](https://replicate.com/)
and billed by them. Gemini 3.5 Flash and Flash-Lite call Google directly.

**Portable conversations.** History lives in the gateway, so you can start a chat on one
model and continue it on another. Each request includes the last four exchanges as
**short-term memory**. A vector-search **long-term memory** is
[planned](#roadmap-long-term-memory).

## Architecture

```mermaid
flowchart TB
    C[Client]

    subgraph GW["SentryKey"]
        direction TB
        AUTH["Auth<br/>key hash → api_key → user"]
        ENT["Entitlement<br/>subscription tier ≥ model tier"]
        COUNT["Count prompt<br/>tiktoken / count_tokens"]
        OWN["Ownership<br/>conversation_id belongs to key"]
        CTX["Short-term memory<br/>lock key row → context SUM → last 8 messages that fit"]
        QUOTA["Reserve<br/>token SUM → insert reservation (tokens + context)"]
        PROV["Provider client"]
        SETTLE["Settle<br/>reservation → real usage + messages"]
        REL["Release<br/>reservation → 0 tokens"]
    end

    OAI["OpenAI"]
    ANT["Anthropic"]
    GEM["Google<br/>Gemini API / Replicate"]
    R[Client response]
    PG[("PostgreSQL")]

    C -->|Bearer key| AUTH --> ENT --> COUNT --> OWN --> CTX --> QUOTA --> PROV
    PROV -->|openai| OAI
    PROV -->|anthropic| ANT
    PROV -->|google| GEM
    OAI --> SETTLE
    ANT --> SETTLE
    GEM --> SETTLE
    SETTLE -->|JSON| R
    PROV -.->|exception / cancellation| REL

    GW -.-> PG
```

A request goes through these steps in order:

1. **Auth and entitlement** run as a FastAPI dependency, before the route handler.
2. **The prompt is counted** with the model's own tokenizer. For Claude this is a network
   call, so it happens before any lock is taken.
3. **Ownership and quota** are checked. A caller who isn't allowed never triggers a
   provider call.
4. **The provider is called.** The database transaction is committed first, so a slow
   stream never holds a connection, transaction or row lock.
5. **Usage is settled**, even if the stream failed partway. Tokens already generated are
   still billed.

## Design

### Keys

**Raw keys are never stored.** Only a SHA-256 hash and a short display prefix are saved.
A leaked database dump can't be used to make requests. A lost key is replaced, not
recovered.

**Keys are revoked, not deleted.** Revoking sets `revoked_on`. The key stops working, but its
conversations and usage records stay for billing and audit.

### Entitlement

Users have no tier column. Their plan comes from the active row in `subscriptions`, which has
start and end dates. Expiry happens on its own; nothing has to flip a flag.

Tiers have a numeric `rank`: Basic 10, Pro 20, Premium 30. A request is allowed if the
subscription's rank is at least the model's minimum rank.

### The usage ledger

Every request writes a row to `usage_records` with the real token counts from the provider.
Remaining quota is a `SUM` over the last 24 hours of rows. Nothing keeps a running counter,
so nothing can drift, and multiple servers agree without coordinating.

An index on `(api_key_id, requested_at)` lets each `SUM` jump straight to one key's last 24
hours instead of reading the whole ledger, so it stays fast as the table grows. A second,
partial index on `requested_at` covers only `Reserved` rows, so the reservation sweeper only
reads requests that are still in flight.

### Reserving quota

A plain "check, then call" lets two parallel requests both see the same budget and overspend
it together. So quota is **reserved** before the call:

1. **Lock.** `SELECT ... FOR UPDATE` locks the key's `api_keys` row. Parallel requests on
   the same key wait here, even across servers, because the lock lives in Postgres.
2. **Check.** Before the lock, `max_tokens` is lowered to the model's output limit, so the
   provider never rejects it and no budget is reserved that the model can't use. Under the
   lock, the history is trimmed to the remaining context quota. Then the prompt (already
   counted) is checked against the token quota. `max_tokens` is lowered to whatever is left,
   or the request gets `429`.
3. **Reserve.** A `Reserved` row for `prompt + max_tokens` is inserted, along with the
   history size in `context_tokens`. Committing it releases the lock. The next request's
   `SUM`s already include it. A new conversation is committed at this point too, so a `429`
   leaves nothing behind.
4. **Settle.** After the call, the same row is overwritten with the real token counts.
   Unused budget comes back immediately. If the provider failed before generating anything
   and the request created the conversation, the conversation is deleted in the same commit
   and the response returns `conversation_id: null`.
5. **Release.** If anything raises before settling, including a client disconnect, the row
   is set to 0 tokens with status `Failed`. Any conversation the request created is deleted.

The release runs inside a shielded `anyio.CancelScope`, so a cancellation can't interrupt
it. It only touches rows still marked `Reserved`, so a request cancelled just after settling
keeps its data. If the release itself fails, it is logged and the original error is
re-raised.

The lock is held for a few statements only, never during the provider stream.

**The full `max_tokens` is reserved on purpose.** While a long request runs, a parallel
request on the same key sees that whole budget as spent and may be limited or refused, until
the first one settles and returns what it didn't use. Reserving in smaller steps mid-stream
would free that budget sooner, but it would mean locking again during the stream and could let
a key go over its quota. No race and no overspend is worth more here than squeezing out
parallel throughput.

**Abandoned reservations are swept.** If a worker dies between reserving and settling
(`SIGKILL`, out of memory, host failure), no release runs. So every app process runs a
background sweeper, started with the app and once a minute after that. It sets any row still
`Reserved` after 15 minutes to 0 tokens with status `Expired`. The sweep only touches
`Reserved` rows, so running it from several workers at once is safe. A request that outlives
the timeout and then finishes still overwrites its row with the real usage.

### Short-term memory

Conversations are a plain message log with no model attached. Context is rebuilt on every
request for whichever model is being used, so switching models mid-chat just works.

Each request takes up to the **last 8 messages** (4 user + 4 assistant). They're walked
newest to oldest and kept while they fit the key's remaining context quota. The first one
that doesn't fit is dropped along with everything older. A leading assistant message is
removed so the history always starts with a user turn.

History is billed to the context quota, not the token quota. It's counted under the same
lock and reserved on the same row, so parallel requests can't spend it twice. Older messages
stay in the database but aren't sent to the model.

Each message's `token_count` comes from the model that wrote it, and other models tokenize the
same text differently. So when history written by one model is sent to another, each of those
messages is recounted with the new model's tokenizer and billed at the **larger** of the two
counts, so a model switch never under-bills. Recounts are saved in `message_token_counts`, one
per message per model, so each message is counted only once per model. OpenAI counts locally.
Claude and Gemini make one `count_tokens` call per message, in parallel and before the key is
locked, so only the first request after a switch is slower. If a recount fails, the stored
count is used and the recount is retried next time.

### Streaming and billing

A provider call can fail before, during or after generating tokens. Each case is billed
differently:

- **Fails before the first chunk:** free.
- **Breaks mid-stream:** billed for what was generated, plus a 15-token buffer.
- **Finishes:** billed using the provider's reported usage. If that never arrives, the
  gateway estimates from the streamed text.

The estimate is exact for OpenAI (`tiktoken`). Claude and Gemini have no local tokenizer, so
an interrupted stream is billed at about 4 characters per token, and never less than the
provider's last reported output count.

Each provider sorts its SDK errors into two groups:

- **Never billable:** bad request, auth, permission, not found, rate limit, request too
  large, connection failure. These always happen before generation.
- **Billable if generation started:** 5xx errors, a mid-stream `overloaded_error`,
  timeouts, dropped connections.

Every provider returns the same `provider_response` dataclass, so settling doesn't care which
provider ran. Messages are saved only once generation has started, so a failed call never
adds an empty turn to the history.

### Claude specifics

- Every Claude request carries a system prompt set by `ANTHROPIC_SYSTEM_PROMPT`. It's never
  charged to the user.
- Anthropic's `input_tokens` includes the system prompt, history and new prompt, so it isn't
  used for billing. `prompt_tokens` is the pre-call `count_tokens` count of the prompt alone,
  and that's also what the saved user message stores.
- If Claude refuses (`stop_reason: "refusal"`), the tokens are still billed, because
  Anthropic charges for them. The row is recorded as `Refused` with status code `403`.

### Gemini specifics

- Prompts are counted with Google's `count_tokens`, before any lock is taken.
- Thinking tokens are billed as output, but never saved as context.
- Blocked or refused answers (`SAFETY`, `RECITATION` and similar) are billed and recorded as
  `Refused` with status code `403`.
- `google/gemini-3.1-pro` runs on Replicate. It is sent history as one text prompt, and a
  dropped request cancels the prediction so it stops billing.
- Calls time out after 60 seconds of silence.

### Reasoning tokens

Claude, Gemini and the GPT-5.6 models think before they answer. Thinking tokens are billed to
the token quota like any output, but stored messages only count the visible answer. Thinking is
never sent back as history.

Thinking counts toward `max_tokens`, so a small `max_tokens` can cut the answer off, or leave
nothing for it at all. Each provider's stop signal is checked: `finish_reason: "length"` (OpenAI),
`stop_reason: "max_tokens"` (Claude) and `finish_reason: "MAX_TOKENS"` (Gemini). Replicate
reports no stop reason, so a reply whose output count reached `max_tokens` is treated as cut
off. Such a reply is recorded as `Truncated` and billed in full, and the response's
`error_detail` tells the client to raise `max_tokens`. A cut-off answer is saved like any
other turn. An empty one is not: neither message is saved, so the history never ends on an
unanswered prompt, and a conversation the request created is deleted.

### Migrations

Every table is created by a reversible Alembic revision. The subscription tiers are seeded by
one too. Nothing is altered by hand.

## Running it

**Requirements:** Python 3.14 and Docker.

```bash
git clone https://github.com/goutham-226/SentryKey.git
cd SentryKey

docker compose up -d
cp .env.example .env          # fill in the variables below

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head          # tables + subscription tiers
python -m scripts.model_seed  # model catalog (safe to re-run)

uvicorn app.main:app --reload
```

| Variable | Used for |
| :--- | :--- |
| `DATABASE_URL` | With the bundled Compose file: `postgresql+asyncpg://kq:kq@localhost:5432/kqpostgres` |
| `OPENAI_API_KEY` | OpenAI models |
| `ANTHROPIC_API_KEY` | Claude models and Claude prompt counting |
| `ANTHROPIC_SYSTEM_PROMPT` | System prompt sent with every Claude request |
| `GOOGLE_API_KEY` | Gemini models and Gemini prompt counting |
| `REPLICATE_API_TOKEN` | Gemini 3.1 Pro (served through Replicate) |

All six are required. The app won't start if any is missing.

Two optional variables tune the reservation sweeper:

| Variable | Default | Used for |
| :--- | :--- | :--- |
| `RESERVATION_TIMEOUT_MINUTES` | `15` | Age after which a `Reserved` row counts as abandoned. Keep it above your longest request. |
| `RESERVATION_SWEEP_INTERVAL_SECONDS` | `60` | How often each process sweeps |

Interactive docs are at **http://127.0.0.1:8000/docs**, generated from the code.

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

### Tests

Tests use a separate `sk_test` database in the same container, so your dev data is safe.
Each test starts with empty tables, and no test calls a real provider.

```bash
pip install -r requirements-dev.txt
docker exec -it kq-postgres createdb -U kq sk_test   # first time only

pytest -v
```

CI runs the same suite on every push and pull request to `main`. A flake8 pass runs first
and fails the build on syntax errors or undefined names.

### Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

Each commit then runs YAML checks, a large-file check, private-key detection,
`ruff check --fix` and the full test suite.

## API

| | Method | Path | Description |
| :---: | :--- | :--- | :--- |
| 🔓 | `GET` | `/health` | Liveness check. |
| 🔓 | `POST` | `/v1/auth/register` | Create an account. Password 8–27 characters, name 1–100. `409` if the email exists, `422` on bad input. |
| 🔓 | `GET` | `/v1/models-catalog` | Every active model with its provider and required plan. |
| 🔑 | `POST` | `/v1/keys` | Create an API key (email and password in the JSON body). The full key is shown **once**. `401` on bad credentials. |
| 🔑 | `GET` | `/v1/keys` | List your active keys by prefix. `404` if you have none. |
| 🔑 | `DELETE` | `/v1/keys/{key_id}` | Revoke a key. It returns `401` from then on. `404` if it isn't yours. |
| 🔑 | `POST` | `/v1/subscriptions` | Subscribe to Basic, Pro or Premium for one month. `409` if you already have an active plan. |
| 🔐 | `POST` | `/v1/chat/completions` | Send a prompt, optionally continuing a conversation. See the errors below. |
| 🔐 | `GET` | `/v1/chat-history/{conversation_id}` | Full message log of one of your conversations. `404` if it isn't yours. |

🔓 ![Public](https://img.shields.io/badge/auth-public-brightgreen) &nbsp;&middot;&nbsp; 🔑 ![Auth](https://img.shields.io/badge/auth-password-orange) &nbsp;&middot;&nbsp; 🔐 ![API Key](https://img.shields.io/badge/auth-bearer_token-blue)

`/v1/chat/completions` errors:

| Code | When |
| :--- | :--- |
| `401` | Missing, unknown or revoked key |
| `403` | No active subscription, or the model is above your tier |
| `404` | Unknown or deactivated model, or a `conversation_id` that isn't yours |
| `422` | `max_tokens` isn't positive |
| `429` | Daily token budget used up |
| `500` | A provider's `count_tokens` call failed (nothing is reserved) |

**Why two credentials?** API keys end up in config files and CI secrets, so they leak. A
leaked key can spend quota, but it can't create keys, change the plan or revoke anything.
Those need the account password. That also means you can revoke a lost key without having it.

### Walkthrough

**1. Create a key.**

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

Save the key now; it can't be shown again. Keep the `key_id` too, you need it to revoke the key.

**2. Subscribe.** The plan starts now and lasts one month.

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

**3. Send a prompt.** Leave out `conversation_id` to start a new conversation. Send the
returned id back to continue it. If the first turn fails before the model generates anything,
no conversation is kept and `conversation_id` comes back `null`.

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

`max_tokens` is lowered to the model's output limit and to your remaining budget before the
request is sent, so the provider never rejects it and you can't overspend, even with parallel
requests.

`error_detail` is `null` unless the reply hit `max_tokens` before finishing. Then it explains
that the answer was cut off, and `output` holds whatever was written before the limit.

Model ids by tier:

| Tier | OpenAI | Anthropic | Google |
| :--- | :--- | :--- | :--- |
| Basic | `gpt-5.6-luna` | `claude-haiku-4-5` | `gemini-3.5-flash-lite` |
| Pro | `gpt-5.6-terra` | `claude-sonnet-5` | `gemini-3.5-flash` |
| Premium | `gpt-5.6-sol` | `claude-opus-5` | `google/gemini-3.1-pro` |

The HTTP status is `200` whenever the provider was reached. How the call actually ended is
stored in the usage record:

| Status | Meaning | Billed |
| :--- | :--- | :--- |
| `Completed` | Finished normally. | Provider's reported usage |
| `Interrupted` | Broke mid-stream. `output` has what was generated. | Tokens received + 15 |
| `Truncated` | Hit `max_tokens` before finishing, often because thinking used most of it. `error_detail` says so. An empty reply saves no messages. | Provider's reported usage |
| `Refused` | Claude or Gemini declined to answer. Status code `403`. | Provider's reported usage |
| `Failed` | Failed before the first token. `output` is a "model not available" message; no messages saved. A conversation started by this request is deleted and `conversation_id` is `null`. | Nothing |
| `Expired` | The worker died before settling, and the sweeper released the reservation. The client never got a response. | Nothing |

**4. Read the conversation.**

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

You get `404` both for conversations that don't exist and ones owned by another key, so
nobody can probe for other people's ids.

**5. Switch models.** Send the same `conversation_id` with a different `model`, even from
another provider. The new model gets the earlier turns as context.

Your plan is checked against the model in *this* request. Asha is on Basic, so moving to
`claude-sonnet-5` (Pro) is refused:

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H 'Authorization: Bearer kq_z9_Nuql9B9YsDYmhBfWPvBLvlCeXzIU' \
  -H 'Content-Type: application/json' \
  -d '{
        "model": "claude-sonnet-5",
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

| Tier    | OpenAI models                                  | Anthropic models                                        |
|---------|------------------------------------------------|---------------------------------------------------------|
| Basic   | `gpt-5.6-luna`                                 | `claude-haiku-4-5`                                      |
| Pro     | `gpt-5.6-luna`, `gpt-5.6-terra`                | `claude-haiku-4-5`, `claude-sonnet-5`                   |
| Premium | `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol` | `claude-haiku-4-5`, `claude-sonnet-5`, `claude-opus-5`  |

On Pro, the same request works. Claude sees the GPT turns and its reply joins conversation `1`:

```json
{
  "model": "claude-sonnet-5",
  "output": "The AGC software was written in an assembly language...",
  "prompt_tokens": 9,
  "completion_tokens": 402,
  "quota_remaining": 99075,
  "conversation_id": 1,
  "error_detail": null
}
```

How the history carries over:

- The `conversation_id` must belong to your key, or you get `404` before anything is
  reserved. Leaving it out (or sending `0`) starts a new conversation.
- Up to the last 8 messages are sent, trimmed to your context quota as described in
  [Short-term memory](#short-term-memory). Older messages are kept but not sent.
- Messages are sent as plain `role` + `content`. The new model sees earlier replies as if
  it wrote them.
- History counts against the context quota, not the token quota. That's why `prompt_tokens`
  above covers only the new prompt.

The history endpoint shows which model wrote each message:

```json
[
  { "conversation_id": 1, "role": "user",      "message": "Explain the computer programs...", "model": "gpt-5.6-luna",    "timestamp": "..." },
  { "conversation_id": 1, "role": "assistant", "message": "The Apollo Guidance Computer...",  "model": "gpt-5.6-luna",    "timestamp": "..." },
  { "conversation_id": 1, "role": "user",      "message": "Which language was that...",      "model": "claude-sonnet-5", "timestamp": "..." },
  { "conversation_id": 1, "role": "assistant", "message": "The AGC software was written...", "model": "claude-sonnet-5", "timestamp": "..." }
]
```

**6. Revoke a key.** Use the `key_id` from step 1, or find it with `GET /v1/keys`.

```bash
curl -X DELETE http://127.0.0.1:8000/v1/keys/1 \
  -u 'asha@example.com:correct-horse-battery'
```

```json
{ "status": "success" }
```

The key now gets `401` and disappears from `GET /v1/keys`. Its conversations and usage
records are kept.

## Data model

```
subscription_tiers ──< users ──< api_keys ──< conversations ──< messages ──< message_token_counts
        │                             │              │
        └──< subscriptions            └──< usage_records >──┘
                                                │
                             models ────────────┘
```

| Table | Holds |
| :--- | :--- |
| `subscription_tiers` | Basic, Pro, Premium and their ranks |
| `models` | Provider, minimum tier, context window, max-tokens parameter name, output limit, prices per 1M tokens |
| `users` | Accounts |
| `subscriptions` | What a user bought and for how long; the only source of entitlement |
| `api_keys` | Hashed keys, prefixes, quotas, revocation date |
| `conversations` | One per chat thread, owned by a key |
| `messages` | Every turn, with its role, model and token count |
| `message_token_counts` | A message's token count for each other model that used it as history |
| `usage_records` | The ledger: prompt, completion and context tokens plus the outcome of each call |

Deletes cascade differently on purpose:

- Keys and conversations are deleted with their owner.
- Usage records survive when their conversation or model is deleted.
- Keys are revoked rather than deleted, so their cascade never fires in normal use.

## Project layout

```
.
├── .github/workflows/
│   └── python-app.yml           CI: flake8 + pytest against Postgres on every push/PR to main
├── app/
│   ├── main.py                  Routes, and the lifespan that runs the reservation sweeper
│   ├── config.py                Settings from the environment
│   ├── db.py                    Async engine, session factory, get_db
│   ├── deps.py                  Auth dependencies: password, API key, API key + tier check
│   ├── security.py              Password hashing (bcrypt)
│   ├── models.py                SQLAlchemy models (the database schema)
│   ├── schemas.py               Pydantic models (the API contract)
│   └── services/
│       ├── provider_service.py  Request flow: ownership, reservation, short-term memory,
│       │                        provider routing, settle, release and the stale-row sweep
│       ├── open_ai.py           OpenAI streaming, tiktoken counting, error handling
│       ├── anthropic_ai.py      Anthropic streaming, count_tokens, refusals, error handling
│       ├── google_ai.py         Gemini streaming, Replicate fallback, count_tokens, refusals
│       └── provider_data.py     provider_response, the shared result type
├── tests/
│   ├── conftest.py              Test DB setup, cleanup, client and user/key/subscription fixtures
│   ├── test_health.py           GET /health
│   ├── test_auth.py             POST /v1/auth/register
│   ├── test_keys.py             Creating, listing and revoking keys
│   ├── test_subscriptions.py    POST /v1/subscriptions
│   ├── test_catalog.py          GET /v1/models-catalog, hiding deactivated models
│   ├── test_chat_history.py     GET /v1/chat-history: format, order, 404s
│   ├── test_deps.py             Auth and tier checks: bad/revoked keys, no plan, wrong tier
│   ├── test_reservations.py     Sweeping abandoned reservations
│   ├── test_chat_completions.py POST /v1/chat/completions with a fake provider: conversation
│   │                            cleanup, truncated and empty replies, max_tokens capping,
│   │                            history recount after a model switch
│   ├── test_usage_indexes.py    Ledger indexes exist and are used by the quota and sweep queries
│   ├── test_providers.py        Each provider module with a fake SDK stream: Truncated vs Completed
│   ├── test_security.py         Password hashing
│   └── test_schemas.py          Request/response validation
├── alembic/versions/            One reversible migration per schema change
├── scripts/
│   ├── model_seed.py            Seeds the model catalog (safe to re-run)
│   └── provider_test.py         Manual smoke test against Replicate
├── sql/                         Original hand-written schema and reporting queries
├── docs/                        Notes on provider SDKs and error handling
├── .env.example                 Required environment variables
├── .pre-commit-config.yaml      Pre-commit hooks
├── alembic.ini                  Alembic config
├── docker-compose.yaml          PostgreSQL 17 with a health check
├── pytest.ini                   Pytest config
├── requirements.txt             Runtime dependencies
└── requirements-dev.txt         Runtime + test dependencies
```

Input and output schemas are always separate classes. A client can't set a server-owned
field because the input model doesn't have it. A secret can't leak because the output model
doesn't have it either.

## Roadmap: long-term memory

Short-term memory only covers the last four exchanges. Anything older, like a name mentioned
early on or a decision from yesterday's chat, is stored but never seen by the model.

Long-term memory will bring back the relevant parts. It is **not built yet**. The plan:

1. **Embed on write.** When a turn settles, embed its messages and store the vectors in
   Postgres (e.g. with `pgvector`), under the same ownership rules as the messages.
2. **Search on read.** Before calling the provider, embed the new prompt and search the
   key's older messages, in this conversation and past ones. Keep only close matches.
3. **Add to context.** Put the matches before the short-term history, marked as recalled.
   Short-term memory always gets the budget first.
4. **Bill it.** Recalled tokens count against the context quota, and embedding calls go in
   the ledger.

Every search is filtered by `api_key_id`, so one key can never recall another key's messages.

## Known flaws

**Already fixed:**

- Parallel requests could overspend the quota. Now a locked reservation.
- A request could write into another key's conversation. Now a `404` before anything is
  reserved.
- The prompt estimate used a word count. Now `tiktoken`.
- The prompt was counted twice per request. Now counted once and passed down.
- History wasn't reserved, so parallel requests could overspend the context quota. It's
  now trimmed under the lock and stored on the reservation row.
- A `429` left an empty conversation behind. The conversation is now committed with the
  reservation.
- A cancellation just after settling could wipe the settled row. Release now only touches
  `Reserved` rows.
- Chat history crashed with a 500 on an unknown conversation id. It now returns `404`.
- Reasoning tokens inflated stored message sizes and context billing. Messages now store
  visible tokens only.
- Deactivated models were still usable in chat. They now get `404`.
- Empty assistant messages broke later Claude requests. They are now skipped when history is
  built.
- A crashed worker left its reservation counting against the key for 24 hours. A background
  sweeper now releases `Reserved` rows older than 15 minutes.
- A first turn that failed before generating left an empty conversation behind. It's now
  deleted when the reservation is settled, and the response returns `conversation_id: null`.
- The quota `SUM`s read the whole usage ledger on every request, while the key was locked.
  An index on `(api_key_id, requested_at)` now takes them straight to one key's last 24 hours.
- Replies cut off by `max_tokens` (often by thinking) were reported as `Completed`, and empty
  ones were still saved. They're now `Truncated` with an `error_detail`, and empty replies
  save no messages.
- `max_tokens` above a model's output limit (e.g. 64K on Claude Haiku 4.5) got a `400` from
  the provider and a generic "model not available" message. It's now lowered to the limit
  stored in `models.max_output_tokens` before anything is reserved.
- `GET /v1/models-catalog` listed deactivated models that chat would reject. It now only lists
  active ones.
- Claude prompts were billed and stored with the system prompt included, so every Claude
  user message over-counted history by the size of `ANTHROPIC_SYSTEM_PROMPT`. Claude now bills
  and stores the prompt's own count, and the system prompt is never charged.
- After a model switch, history was billed and trimmed with the old model's token counts,
  usually under-billing it on Claude. Messages from another model are now recounted with the
  current model, saved once per model, and billed at the larger count.



## License

MIT, see [LICENSE](LICENSE).
