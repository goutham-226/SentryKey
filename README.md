<div align="center">

# SentryKey

**A multi-provider AI gateway with metered access, tiered models, and persistent conversation memory.**

One OpenAI-shaped endpoint in front of nine models across six providers. Authenticates by
API key, enforces a daily token budget, remembers the conversation, and caches what it can.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Alembic](https://img.shields.io/badge/Alembic-migrations-6BA81E?style=flat-square)](https://alembic.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-cache-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

[Overview](#overview) &nbsp;&middot;&nbsp;
[Architecture](#architecture) &nbsp;&middot;&nbsp;
[Design](#design) &nbsp;&middot;&nbsp;
[Running it](#running-it) &nbsp;&middot;&nbsp;
[API](#api) &nbsp;&middot;&nbsp;
[Data model](#data-model)

</div>

---

## Overview

Talking to several model providers directly means several SDKs, several billing accounts,
several sets of credentials, and no single answer to "what did this cost and who spent it."

**SentryKey** is the layer that fixes that. It exposes one endpoint, routes to whichever
model the caller asked for, and owns everything that sits between a request and an
inference call: who is asking, whether they are entitled to that model, how much they have
spent today, what the conversation so far consisted of, and whether this answer already
exists in cache.

Access is tiered. Three subscription plans map to nine models, so a basic subscriber
reaches open-weight models, a pro subscriber reaches mid-tier hosted models, and a premium
subscriber reaches the frontier ones — enforced at the gateway rather than trusted to the
client.

## Architecture

```mermaid
flowchart TB
    C[Client]

    subgraph GW["SentryKey"]
        direction TB
        AUTH["Auth<br/>hash → key → user"]
        ENT["Entitlement<br/>subscription → tier → model"]
        QUOTA["Quota<br/>tokens used today"]
        CACHE{"Cache<br/>hit?"}
        CTX["Context assembly<br/>history + retrieval"]
        PROV["Provider client"]
        METER["Usage record"]
    end

    PG[("PostgreSQL<br/>users · keys · usage<br/>conversations · messages")]
    RD[("Redis<br/>response cache<br/>rate limits")]
    VDB[("Vector store<br/>embedded turns")]
    UP["Replicate<br/>9 models"]

    C -->|Bearer key| AUTH --> ENT --> QUOTA --> CACHE
    CACHE -->|hit| METER
    CACHE -->|miss| CTX --> PROV --> UP
    PROV --> METER --> C

    AUTH -.-> PG
    ENT -.-> PG
    QUOTA -.-> PG
    CACHE -.-> RD
    CTX -.-> PG
    CTX -.-> VDB
    METER -.-> PG
```

Authentication, entitlement and quota run as dependencies before the handler is reached, so
no request body is parsed and no upstream call is made on behalf of a caller who was never
going to be allowed one.

## Design

Five constraints shape the implementation. Each rules out the obvious naive approach.

**Raw keys are never stored.** Only a SHA-256 digest and a short display prefix are
persisted. Authentication hashes the presented key and looks up the digest, so the lookup
stays a single indexed query while a database dump stays unusable. A lost key is replaced,
never recovered.

**Entitlement is derived, never cached on the user.** A user has no tier column. The active
subscription — a dated row, not a flag — is the only answer to what they may reach, so
expiry is a fact about time rather than a state something must remember to update.

**Spend is a ledger, not a counter.** Every request writes a usage row with real token
counts from the provider. Remaining quota is a `SUM` over today's rows, served by a
composite index. Nothing increments a running total, so nothing can drift, and several
replicas agree without coordinating.

**Context is assembled per request, against the model being used now.** Windows differ by
two orders of magnitude across the catalog, so a conversation is a message log with no model
attached and the truncation budget is recomputed every turn. Switching models mid-thread is
therefore a supported operation rather than a corruption.

**Schema changes go through migrations.** Every table is defined by a reversible Alembic
revision. No table is altered by hand, in any environment.

## Running it

**Requirements:** Python 3.12+, Docker

```bash
git clone https://github.com/goutham-226/SentryKey.git
cd SentryKey

docker compose up -d
cp .env.example .env          # set DATABASE_URL and provider credentials

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head          # schema, plus the subscription tiers
python -m scripts.seed_models # the model catalog

uvicorn app.main:app --reload
```

Interactive documentation is served at **http://127.0.0.1:8000/docs**, generated from the
route signatures and Pydantic models, so it never drifts from the code.

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

Developing over SSH? Forward the port rather than binding to `0.0.0.0`:

```bash
ssh -L 8000:localhost:8000 user@host
```

## API

| | Method | Path | Description |
| :---: | :--- | :--- | :--- |
| 🔓 | `GET` | `/health` | Liveness probe. Unversioned — infrastructure, not API surface. |
| 🔓 | `POST` | `/v1/auth/register` | Create an account. `409` on a duplicate email. |
| 🔓 | `GET` | `/v1/models-catalog` | The public catalog: every active model and the plan it needs. |
| 🔑 | `POST` | `/v1/keys` | Issue an API key. The raw value is returned **once**. |
| 🔑 | `GET` | `/v1/keys` | List the caller's keys by prefix, with quota and revocation state. |

🔓 public &nbsp;&middot;&nbsp; 🔑 email and password &nbsp;&middot;&nbsp; 🔐 `Authorization: Bearer <key>`

Two credentials, deliberately. Key management requires the account password, because an API
key is a bearer credential that lives in config files and CI variables — a leaked key can
spend quota, but it cannot mint more keys or escalate.

### Example

```bash
curl -X POST http://127.0.0.1:8000/v1/keys \
  -u 'asha@example.com:correct-horse-battery' \
  -H 'Content-Type: application/json'
```

```json
{
  "api_key": "kq_z9_Nuql9B9YsDYmhBfWPvBLvlCeXzIU",
  "daily_quota": 100000
}
```

That value is shown once and cannot be retrieved. Only its first eleven characters and a
hash are stored.

## Data model

```
subscription_tiers ──< users ──< api_keys ──< conversations ──< messages
                                      │              │
                                      └──< usage_records >──┘
                                                │
                             models ────────────┘
```

Seven tables. `subscription_tiers` and `models` are catalog data — a model launch, a price
change or an emergency deactivation is an `UPDATE`, never a deploy. `subscriptions` records
what a user bought and for how long. `usage_records` is the ledger every quota decision and
every cost report is derived from.

Cascades differ per relationship, deliberately: keys and conversations cascade from their
owner, usage records keep their row when a conversation is deleted, and a retired model
never rewrites history.

## Project layout

```
.
├── app/
│   ├── main.py            Routes
│   ├── config.py          Settings from the environment
│   ├── db.py              Async engine, session factory, get_db
│   ├── deps.py            Auth dependencies — password and API key
│   ├── security.py        Password hashing, key generation
│   ├── models.py          SQLAlchemy ORM — the database schema
│   └── schemas.py         Pydantic — the API contract
├── alembic/versions/      One reversible revision per schema change
├── scripts/               Catalog seeding
├── sql/                   The original hand-written schema and reporting queries
├── docker-compose.yaml    PostgreSQL 17, named volume, health check
└── requirements.txt
```

Input and output schemas are kept separate throughout. A client cannot set a server-owned
field, because no such field exists on the input model; a secret cannot leak, because the
response model does not declare it. Both hold by construction rather than by review.

## License

MIT — see [LICENSE](LICENSE).
