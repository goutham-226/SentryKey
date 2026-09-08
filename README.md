<div align="center">

# Key &amp; Quota Service

**API key issuance, Bearer authentication, and per-key usage metering.**

Issue keys to users, authenticate every request against them, record what each call costs,
and refuse the calls that exceed a key's monthly allowance.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Alembic](https://img.shields.io/badge/Alembic-6BA81E?style=flat-square&logo=alembic&logoColor=white)](https://alembic.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

[Overview](#overview) &nbsp;&middot;&nbsp;
[Design](#design) &nbsp;&middot;&nbsp;
[Running it](#running-it) &nbsp;&middot;&nbsp;
[API](#api) &nbsp;&middot;&nbsp;
[Architecture](#architecture)

</div>

---

## Overview

Every service exposed to more than one consumer eventually needs the same four things:
a way to identify who is calling, a record of what they called, a limit on how much they
may call, and a way to cut a caller off without redeploying.

**Key &amp; Quota Service** is that layer, built standalone. It issues API keys tied to
users, authenticates incoming requests by hashed key, writes a usage record for every
call, and enforces a per-key monthly token allowance.

It is also the authentication and metering core of an OpenAI-compatible AI gateway,
built in isolation so that key handling, aggregation at scale, and quota contention are
solved without an inference backend in the way.

## Design

Four constraints shape the implementation. Each rules out the obvious naive approach.

**Raw keys are never stored.** Only a one-way hash and a short display prefix are
persisted. A database dump cannot be replayed against the API, and a key that is lost is
lost — there is no recovery path, only reissue.

**Usage aggregation stays fast at ten million rows.** Monthly totals are served by a
composite index on `(api_key_id, requested_at)`, not a sequential scan. Query plans are
verified with `EXPLAIN ANALYZE` rather than assumed.

**Quota cannot be overspent under concurrency.** Two simultaneous requests against a key
with room for one must not both succeed. The check is enforced in the database, because a
read-then-write in application code can always be interleaved.

**Schema changes go through migrations.** Every table is defined by a reversible Alembic
revision. No table is altered by hand, in any environment.

## Running it

**Requirements:** Python 3.12+, Docker

```bash
git clone https://github.com/goutham-226/key-quota-service.git
cd key-quota-service
```

Start PostgreSQL:

```bash
docker compose up -d
```

Configure the environment — copy `.env.example` to `.env` and set the connection string:

```
DATABASE_URL=postgresql+asyncpg://kq:kq@localhost:5432/kqpostgres
```

Install dependencies, apply migrations, and run:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head
uvicorn app.main:app --reload
```

Interactive API documentation is served at **http://127.0.0.1:8000/docs**, generated from
the route signatures and Pydantic models, so it never drifts from the code.

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

Optionally load sample data:

```bash
docker exec -i kq-postgres psql -U kq -d kqpostgres < sql/002_seed.sql
```

## API

| | Method | Path | Description |
| :---: | :--- | :--- | :--- |
| 🔓 | `GET` | `/health` | Liveness probe. Unversioned — infrastructure, not API surface. |
| 🔓 | `POST` | `/v1/users` | Create a user. `409` on duplicate email. |
| 🔓 | `GET` | `/v1/users` | List users, paginated via `limit` (1–100) and `offset`. |
| 🔓 | `POST` | `/v1/echo` | Metered endpoint. Returns a transformed prompt and its token count. |

🔓 public &nbsp;&middot;&nbsp; 🔐 requires `Authorization: Bearer <key>`

### Example

```bash
curl -X POST http://127.0.0.1:8000/v1/echo \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "hello world"}'
```

```json
{
  "output": "dlrow olleh",
  "tokens_used": 2
}
```

## Architecture

```
.
├── app/
│   ├── main.py              FastAPI application and routes
│   ├── config.py            Settings loaded from the environment
│   ├── db.py                Async engine, session factory, get_db dependency
│   ├── models.py            SQLAlchemy ORM models — the database schema
│   └── schemas.py           Pydantic models — the API contract
├── alembic/
│   ├── env.py               Migration environment, wired to app settings
│   └── versions/            One reversible revision per schema change
├── sql/
│   ├── 001_schema.sql       Original hand-written schema, kept for reference
│   ├── 002_seed.sql         Sample data for local development
│   └── queries.sql          Usage and quota reporting queries
├── alembic.ini
├── docker-compose.yaml      PostgreSQL 17 with a named volume and health check
└── requirements.txt
```

**Three tables.** `users` owns identity, `api_keys` holds one row per issued credential
with its own quota and revocation timestamp, and `usage_records` accumulates one row per
metered request. Keys cascade from users and usage cascades from keys, so removing an
account leaves nothing orphaned.

**Alembic is the source of truth for the schema.** The SQL in `sql/001_schema.sql` is the
original hand-written version, kept because it states the design more plainly than a
migration does — but the database is built from `alembic upgrade head`, and nothing is
altered by hand.

**Input and output models are kept separate throughout.** A client cannot set a
server-owned field, because no such field exists on the input model. A server-side secret
cannot leak, because the response model does not declare it. Both properties hold by
construction rather than by review.

**Resources arrive by dependency injection.** The database session is created per request
and closed after the response is sent, including on error paths. Settings and the
authenticated key resolve through the same mechanism, which keeps handlers free of setup
code and makes every one of them substitutable under test.

## License

MIT — see [LICENSE](LICENSE).
