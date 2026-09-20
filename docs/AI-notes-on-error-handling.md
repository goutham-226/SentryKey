"""
Minimal end-to-end example of the pattern: error handling + usage logging.

Read it in this order:
  1. errors        - your vocabulary
  2. UsageDraft    - the record every layer writes into
  3. call_openai   - the ONLY place provider exceptions exist
  4. middleware    - creates the draft, writes it in finally
  5. handler       - turns your errors into responses
  6. the route     - three phases, no try/except around the call

Fake DB calls are marked TODO so the structure stays visible.

================================ NOTES =====================================
THE SHAPE OF THE WHOLE THING

Three concerns are separated and never mixed:

  - where errors are BORN      -> the adapter (3). Only place provider
                                  exceptions exist.
  - where errors become HTTP   -> the handler (5). Only place status codes
                                  and user-facing strings get chosen.
  - where errors get RECORDED  -> middleware + draft (2, 4). A write that
                                  happens on every path, including crashes.

The route (6) knows about none of this, which is why it reads as the happy
path top to bottom. That is the entire payoff: business logic doesn't get
buried under error plumbing.
============================================================================
"""

import asyncio
import time
from dataclasses import dataclass, field, asdict
from uuid import uuid4

import openai
from openai import AsyncOpenAI
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------- 1. errors

class GatewayError(Exception):
    """status_code = what the client sees, error_code = what you group on."""
    # NOTE: two different numbers on purpose.
    #   status_code - a CONTRACT decision. What the caller sees.
    #   error_code  - an INTERNAL decision. What you group on in metrics and
    #                 store in usage_records.
    # Keeping them separate means five distinct internal failure modes can all
    # surface as 502 without losing the ability to ask "how many of last
    # night's 502s were timeouts vs malformed upstream responses?"
    status_code = 500
    error_code = "internal_error"

    def __init__(self, provider_error: dict | None = None):
        # NOTE: this is THE leak boundary. Provider error bodies routinely
        # contain your org id, your key prefix, internal model names, and
        # rate-limit headers that reveal your account tier. It rides along on
        # the exception so it can be logged, and never enters a response.
        self.provider_error = provider_error  # INTERNAL ONLY, never in a response
        super().__init__(self.error_code)


class QuotaExhausted(GatewayError):
    # NOTE: 429 is honest here - the caller genuinely exceeded THEIR limit,
    # and retrying later actually helps.
    status_code, error_code = 429, "quota_exhausted"

class ContextLengthExceeded(GatewayError):
    # NOTE: caller's fault AND deterministic. Retrying the identical request
    # always fails, so 400 (don't retry) rather than 5xx (do retry).
    status_code, error_code = 400, "context_length_exceeded"

class UpstreamRateLimited(GatewayError):
    # NOTE: the subtle one. 503, NOT 429.
    # 429 tells the caller "you sent too much" - that would be a lie. They did
    # nothing wrong; your shared upstream capacity ran out. 503 says "service
    # temporarily unavailable", which is true, and signals retry-with-backoff.
    status_code, error_code = 503, "upstream_rate_limited"

class UpstreamTimeout(GatewayError):
    # NOTE: standard gateway semantics. You are literally a gateway.
    status_code, error_code = 504, "upstream_timeout"

class UpstreamError(GatewayError):
    # NOTE: catch-all for "upstream said something I can't act on".
    status_code, error_code = 502, "upstream_error"

class UpstreamAuthFailed(GatewayError):
    # OpenAI rejected YOUR key -> 500, not 401.
    # NOTE: the original comment here read "A 401 would send the user off to
    # check their own key, which is fine." That's backwards - fixed below.
    # A 401 would send them hunting through their own credentials for a
    # problem that doesn't exist there. From the caller's side this is
    # unambiguously your bug: nothing they can do. Hence 500.
    status_code, error_code = 500, "upstream_auth_failed"


# NOTE: constants, not f-strings - and that's a structural guarantee, not a
# style choice. If the message is ALWAYS looked up by error_code, there is no
# code path where a provider string can be interpolated into a client-visible
# response. You can't leak what you can't interpolate.
# Secondary win: these strings are stable, so clients can branch on
# error.code, and localisation later happens in exactly one place.
MESSAGES = {
    "quota_exhausted":         "Daily token quota exhausted.",
    "context_length_exceeded": "Request exceeds the context window for this model.",
    "upstream_rate_limited":   "Model capacity is temporarily exhausted.",
    "upstream_timeout":        "The model provider did not respond in time.",
    "upstream_error":          "The model provider returned an unexpected response.",
    "upstream_auth_failed":    "The gateway could not reach the model provider.",
    "internal_error":          "An unexpected error occurred.",
}


# ----------------------------------------------------------- 2. usage draft

@dataclass
class UsageDraft:
    """One per request. Each layer fills in what it knows.
    The log helper takes this single object - not 12 arguments."""
    # NOTE: one mutable object per request, created before anything can fail,
    # parked on request.state, filled in progressively:
    #   middleware -> request_id
    #   route      -> api_key_id, model, then tokens and billable
    #   handler    -> status_code, error_code, provider_error
    #
    # The alternative - log_usage(a, b, c, d, ...) at each exit point - breaks
    # down fast: you'd need a call at every raise site and every return, each
    # with a different subset of the information available. The draft turns
    # "log the request" into "write down what you know as you learn it", and
    # one finally block does the actual write.
    request_id: str
    api_key_id: int | None = None
    model: str | None = None
    status_code: int | None = None
    error_code: str | None = None

    # NULLABLE on purpose: None = "we don't know", 0 = "we know it was zero".
    # NOTE: these are different CLAIMS ABOUT THE WORLD and collapsing them
    # corrupts everything downstream:
    #   - billing reconciliation against the provider invoice needs to know
    #     which rows are genuinely unbilled vs unknown
    #   - AVG(input_tokens) over rows with a fake 0 is silently wrong
    #   - WHERE input_tokens IS NULL is a clean query for "rows I must
    #     reconcile by hand"
    # General DB habit: NULL is not a worse version of zero. Resist making a
    # column NOT NULL DEFAULT 0 just because nullable feels untidy - you're
    # discarding a distinction you can never recover.
    input_tokens: int | None = None
    output_tokens: int | None = None

    # NOTE: separates "we returned HTTP 200" from "the provider ran a
    # completion and will charge us". A timeout is billable-unknown. A quota
    # rejection is definitely not billable. A successful call that then failed
    # to persist in phase 3 IS billable even though the caller got a 500.
    # This flag is what answers "how much did we spend on requests the user
    # never saw?"
    billable: bool = False

    provider_error: dict | None = None


# -------------------------------------------------------------- 3. adapter

# NOTE: this whole section is the anti-corruption layer. The invariant is in
# the docstring below: NOTHING ABOVE THIS FUNCTION EVER IMPORTS openai.
# Everything upstream speaks only GatewayError. That's what makes "add
# Anthropic and Google" a matter of writing two more adapters that raise the
# same exception types, with zero changes to the route, handler, or middleware.

# NOTE: max_retries and timeout are explicit ON PURPOSE. The SDK retries by
# default whether or not you ask. Writing it down prevents the classic mistake
# of wrapping this call in your own retry loop and quietly getting 3 x 3 = 9
# attempts, 3x the latency budget, and 3x the bill.
client = AsyncOpenAI(max_retries=2, timeout=30.0)  # explicit: SDK already retries


@dataclass
class Result:
    # NOTE: narrow contract. Upper layers never touch the SDK's response shape,
    # so a provider changing its response schema is a one-file problem.
    text: str
    input_tokens: int
    output_tokens: int


async def call_openai(model: str, messages: list) -> Result:
    """Catches openai.* and raises GatewayError. Nothing above this
    function ever imports openai."""
    try:
        r = await client.chat.completions.create(model=model, messages=messages)

    # NOTE ON ORDERING - this is load-bearing.
    # RateLimitError, AuthenticationError and BadRequestError are all
    # SUBCLASSES of APIStatusError. Python matches except clauses top to
    # bottom, so the base class MUST come last. Move APIStatusError up two
    # lines and every 400 and 429 silently becomes a generic 502.
    # APITimeoutError sits outside that hierarchy (it descends from the
    # connection-error side), which is why it's handled separately.

    except openai.APITimeoutError:
        # Timeout means WE gave up waiting, not that they stopped working.
        # Tokens may well have been consumed -> leave them None, not 0.
        # NOTE: the provider may have generated and billed a full completion
        # that arrived two seconds after you gave up. Writing 0 here would be
        # asserting something you don't know.
        raise UpstreamTimeout({"provider_status": None,
                               "provider_error_type": "APITimeoutError"})

    except openai.RateLimitError as e:
        raise UpstreamRateLimited(_capture(e))

    except openai.AuthenticationError as e:
        raise UpstreamAuthFailed(_capture(e))

    except openai.BadRequestError as e:
        # The one ambiguous status: their fault or yours? Read the code.
        # NOTE: a provider 400 could mean the CALLER sent something invalid
        # (prompt longer than the context window) or that YOUR gateway built a
        # malformed request. Defaulting an unrecognised 400 to "my bug" is the
        # right instinct: a 400 returned to the caller is an accusation, and
        # you shouldn't accuse someone until you've confirmed they're at fault.
        code = (e.body or {}).get("error", {}).get("code")
        if code == "context_length_exceeded":
            raise ContextLengthExceeded(_capture(e))
        raise GatewayError(_capture(e))  # unrecognized -> assume it's your bug

    except openai.APIStatusError as e:
        raise UpstreamError(_capture(e))  # base class: any other status

    except asyncio.CancelledError:
        # NOTE: not an error - the client hung up, or a timeout is unwinding
        # the task. asyncio's cancellation model DEPENDS on this exception
        # reaching the top; catching it and continuing leaves you with a task
        # that was told to stop and didn't. The except Exception clauses
        # elsewhere won't catch it either (3.8+: it inherits BaseException),
        # but writing it explicitly documents the intent and protects against
        # someone later adding a broad handler above it.
        raise  # NOT an error - the user hung up. Never swallow this.

    # NOTE: turns a structurally valid but useless response into an
    # UpstreamError AT THE BOUNDARY, rather than letting None flow into
    # result.text and blow up three layers up in unrelated code.
    # CAVEAT for later: message.content is also legitimately None when the
    # model returns a tool call or a refusal object, so this check needs to
    # grow once you add function calling.
    if not r.choices or r.choices[0].message.content is None:
        raise UpstreamError({"provider_error_type": "empty_response"})

    return Result(r.choices[0].message.content,
                  r.usage.prompt_tokens, r.usage.completion_tokens)


def _capture(e: openai.APIStatusError) -> dict:
    # NOTE: exactly the four things worth keeping.
    return {
        "provider_status": e.status_code,
        "provider_error_type": (e.body or {}).get("error", {}).get("code"),
        # NOTE: quote this verbatim in a support ticket - it's how the
        # provider finds your specific request in their own logs.
        "provider_request_id": e.request_id,  # quote this in support tickets
        # NOTE: the [:2000] is not cosmetic. This string goes straight into a
        # Postgres column and into your logs; one pathological provider
        # response shouldn't be able to write a megabyte per request.
        "raw": str(e.body)[:2000],
    }


# ----------------------------------------------------------- 4. the logging

async def persist_usage(draft: UsageDraft):
    """Own session, always. If the request died mid-transaction the
    request-scoped session is poisoned and this would raise."""
    # NOTE: two concrete reasons for the separate session:
    #   1. if the request died mid-transaction, the request-scoped session is
    #      in a failed state - SQLAlchemy raises PendingRollbackError on any
    #      further statement until you roll back.
    #   2. by the time a finally in middleware runs, a dependency-managed
    #      session has typically already been CLOSED.
    # A logging write that only works when nothing went wrong is a logging
    # write that fails precisely when you need it.
    try:
        async with SessionLocal() as db:          # TODO
            db.add(UsageRecords(**asdict(draft)))  # TODO
            await db.commit()
    except Exception:
        # Swallow: a DB hiccup must never turn a 200 into a 500.
        # NOTE: one of the few places a blanket swallow is correct, and the
        # justification has to be stated - usage logging is OBSERVABILITY, not
        # business logic. The print fallback means the data still lands in
        # stdout where your log shipper can pick it up.
        print("usage_write_failed", asdict(draft))


app = FastAPI()


@app.middleware("http")
async def usage_logging(request: Request, call_next):
    # NOTE: the draft is created as the middleware's FIRST act - before auth,
    # before validation, before the route. So there is no request that can
    # fail early enough to produce no record at all.
    request.state.draft = UsageDraft(request_id=str(uuid4()))
    try:
        return await call_next(request)
    except asyncio.CancelledError:
        request.state.draft.error_code = "client_disconnected"
        raise
    except Exception:
        # Unhandled exceptions propagate THROUGH middleware instead of
        # arriving as a response. Without this, the errors you most want
        # logged are the ones that never get logged.
        # NOTE: it records, then re-raises, so Starlette's default 500
        # handling still happens.
        request.state.draft.status_code = 500
        request.state.draft.error_code = "internal_error"
        raise
    finally:
        await persist_usage(request.state.draft)

    # ------------------------------------------------------------------
    # NOTE - TWO GAPS IN THIS MIDDLEWARE, both of which you will hit:
    #
    # 1. GatewayError NEVER reaches the except clause above. Registered
    #    exception handlers run INSIDE the middleware stack, so by the time
    #    the middleware sees it, the handler (5) has already converted it to
    #    a JSONResponse. That is exactly why the handler writes to the draft
    #    itself. This except only fires for genuinely unhandled exceptions.
    #
    # 2. Anything producing a non-GatewayError HTTP response - Pydantic's 422
    #    on a malformed body, a 401 from the auth dependency, a 404 - logs
    #    with status_code = None, because only the route's success path and
    #    the GatewayError handler ever write that field. Fix: capture the
    #    response in a variable, read response.status_code into the draft,
    #    then return it, so the finally sees a real number.
    # ------------------------------------------------------------------


# -------------------------------------------------------------- 5. handler

# NOTE: the single place where a GatewayError becomes bytes on the wire.
# Two jobs: finish the draft, and build the response. The route never
# constructs an error response itself - that's what keeps section 6 readable.

@app.exception_handler(GatewayError)
async def on_gateway_error(request: Request, exc: GatewayError):
    draft = request.state.draft
    draft.status_code = exc.status_code
    draft.error_code = exc.error_code
    draft.provider_error = exc.provider_error   # stays internal

    # Tokens: 0 when we know nothing ran, left as None when we can't know.
    # NOTE: read the condition as "set 0 only where you can PROVE nothing was
    # consumed". Those two excluded codes are the ones where the request may
    # have reached the model:
    #   upstream_timeout - you stopped waiting; generation may have finished
    #   upstream_error   - an unrecognised upstream response; state unknown
    # Everything else (quota, auth, context length) is either rejected before
    # the network call or rejected by the provider without charging.
    if exc.error_code not in ("upstream_timeout", "upstream_error"):
        draft.input_tokens = draft.output_tokens = 0

    # NOTE: the response envelope is a CONTRACT. Stable shape, machine-
    # readable code, human-readable message pulled from the constant table,
    # and the request id in BOTH the body and an X-Request-Id header - body
    # for the application, header for proxies and curl -i, and so a user can
    # quote one id in a support message and you can find the exact row.
    return JSONResponse(
        status_code=exc.status_code,
        headers={"X-Request-Id": draft.request_id},
        content={"error": {"code": exc.error_code,
                           "message": MESSAGES[exc.error_code],
                           "request_id": draft.request_id}},
    )


# ---------------------------------------------------------------- 6. route

# NOTE: dict dispatch instead of if/elif on provider name. Adding a provider
# is: write an adapter that raises GatewayError, add one line here. The route
# body doesn't change.
PROVIDERS = {"openai": call_openai}


@app.post("/v1/chat")
async def chat(payload: ChatRequest, request: Request, api_key=Depends(auth)):  # TODO
    # NOTE: no try/except anywhere in this function. Errors flow up to the
    # handler. That is why the body reads as the happy path, top to bottom.
    draft = request.state.draft
    # NOTE: set these EARLY, so even a request that fails in phase 1 is still
    # attributed to a key and a model in usage_records.
    draft.api_key_id = api_key.id
    draft.model = payload.model

    # PHASE 1 - read. Session opened, used, closed.
    async with SessionLocal() as db:                                    # TODO
        model_row = await get_model(db, payload.model)                  # TODO
        if api_key.tokens_used >= api_key.daily_quota:
            raise QuotaExhausted()
        # filter by api_key_id or anyone can read another user's history
        # NOTE: classic IDOR. If conversation_id alone selects the rows, any
        # caller who guesses or increments an id reads someone else's chat.
        # Ownership must be part of the WHERE clause, never assumed.
        history = await load_history(db, payload.conversation_id, api_key.id)  # TODO

    # PHASE 2 - network. NO SESSION HELD. This is the whole point.
    # NOTE: the single most important scaling decision in the file.
    # A DB connection pool is small (tens). An LLM call takes seconds and is
    # capped here at 30s. Hold a connection across that call and N concurrent
    # requests means N connections parked doing nothing; the pool empties and
    # requests that only need a 2ms SELECT start queuing behind model calls.
    # Your throughput ceiling becomes pool_size / llm_latency instead of
    # pool_size / query_latency - two orders of magnitude worse.
    result = await PROVIDERS[model_row.provider](model_row.name, history)

    draft.input_tokens = result.input_tokens
    draft.output_tokens = result.output_tokens
    draft.billable = True   # NOTE: set the moment the provider succeeded,
                            # BEFORE phase 3. If the write below explodes, the
                            # usage row still says you were charged.

    # PHASE 3 - write. New session, one transaction, one commit.
    # NOTE: both statements in one transaction so you can't save the turn and
    # then fail to charge for it (or vice versa). One commit = atomic.
    async with SessionLocal() as db:                                    # TODO
        await save_turn(db, payload, result)                            # TODO
        await decrement_quota(db, api_key.id,
                              result.input_tokens + result.output_tokens)
        await db.commit()

    draft.status_code = 200
    return {"reply": result.text, "request_id": draft.request_id}


# ============================== OPEN ISSUES ================================
# Things this file deliberately doesn't solve, worth knowing before you build
# on it:
#
# 1. QUOTA RACE. Phase 1 reads tokens_used and compares; phase 3 writes it
#    back. Two concurrent requests both read the old value and both pass the
#    check - a caller with 100 tokens left can spend 10,000 by firing
#    requests in parallel. decrement_quota must be an atomic statement
#    (UPDATE api_keys SET tokens_used = tokens_used + :n WHERE id = :id),
#    never read-modify-write in Python. Whether you also need a hard
#    pre-reservation depends on how much overage you can tolerate; most
#    gateways accept a small soft overage rather than pay for a lock on every
#    request.
#
# 2. PHASE 3 FAILURE. If the model call succeeds and the write fails, the
#    caller gets a 500 for a completion you were billed for and their turn
#    isn't saved. The draft records billable=True with real token counts, so
#    it's at least reconcilable - but decide deliberately whether you want a
#    retry, an outbox row, or to accept the loss.
#
# 3. NOT COVERED HERE: streaming responses (which break the "tokens known at
#    the end" assumption), idempotency keys, per-key rate limiting as opposed
#    to quota, and request tracing across the gateway boundary.
# ===========================================================================