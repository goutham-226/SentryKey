# OpenAI Python SDK (async) — Dev Notes

Sources: `openai/openai-python` README (main, Sept 2026) and the OpenAI "Conversation state" and "Text generation" guides.
Scope: calling models with `AsyncOpenAI` and feeding prior messages (`role` + `content`).

---

## 1. Install and setup

```bash
pip install openai            # httpx backend (default)
pip install "openai[aiohttp]" # optional aiohttp backend, better for high concurrency (Python 3.10+)
```

- Python 3.9+ required.
- Keep the key in `OPENAI_API_KEY` (e.g. via `.env` + python-dotenv). The client reads it automatically; don't hardcode it.
- Check installed version with `openai.__version__` if a feature seems missing.

```python
from openai import AsyncOpenAI

client = AsyncOpenAI()  # reads OPENAI_API_KEY
```

The async client has the same interface as the sync one; every call is just `await`ed.

### Client lifecycle (important in FastAPI)

- Create **one client per process** and reuse it. It holds a connection pool.
- Close it on shutdown: `await client.close()` or `async with AsyncOpenAI() as client:`.
- In FastAPI, that means creating it in the `lifespan` handler and storing it on `app.state`, not creating a new client per request.

---

## 2. Two APIs: pick one

| | Chat Completions | Responses |
|---|---|---|
| Method | `client.chat.completions.create` | `client.responses.create` |
| Status | Previous standard, supported indefinitely | Current primary API |
| History param | `messages=[...]` | `input=[...]` |
| System prompt | a `system` / `developer` message | `instructions=` param, or a `developer` message |
| Text out | `resp.choices[0].message.content` | `resp.output_text` |
| Server-side state | None — you always send history | Optional: `previous_response_id`, `conversation`, `store` |
| Portability to other providers | High (many providers mimic this shape) | OpenAI-specific |

Both accept the simple `{"role": ..., "content": "..."}` message shape.

---

## 3. Chat Completions with history

Roles: `system` (or `developer`), `user`, `assistant` (also `tool` for tool results).

```python
history = [
    {"role": "developer", "content": "You are a concise assistant."},
    {"role": "user", "content": "knock knock."},
    {"role": "assistant", "content": "Who's there?"},
    {"role": "user", "content": "Orange."},
]

resp = await client.chat.completions.create(
    model="gpt-5.5",
    messages=history,
)

text = resp.choices[0].message.content
history.append({"role": "assistant", "content": text})   # keep the loop going
```

Useful response fields:
- `resp.choices[0].message.content` — the reply
- `resp.choices[0].finish_reason` — `stop`, `length` (hit token limit), `tool_calls`, ...
- `resp.usage.prompt_tokens`, `resp.usage.completion_tokens`, `resp.usage.total_tokens`
- `resp.model` — the exact model snapshot that served it
- `resp._request_id` — log this (public despite the underscore)

The API is **stateless**: the model only knows what's in `messages` on that call.

---

## 4. Responses API with history

### 4a. Manual history (stateless)

Same idea — send alternating `user` / `assistant` messages as `input`:

```python
resp = await client.responses.create(
    model="gpt-5.5",
    instructions="You are a concise assistant.",
    input=[
        {"role": "user", "content": "knock knock."},
        {"role": "assistant", "content": "Who's there?"},
        {"role": "user", "content": "Orange."},
    ],
    store=False,   # don't keep state on OpenAI's side
)
print(resp.output_text)
```

Gotchas:
- `instructions` applies **only to the current request**. Send it every turn.
- For reasoning models, OpenAI recommends replaying **every item in `resp.output`** (including encrypted reasoning items), not just the text. If you only store plain `role/content` text, it still works, but the model loses its prior reasoning context.
- Usage: `resp.usage.input_tokens`, `resp.usage.output_tokens`, `resp.usage.total_tokens`.

### 4b. Server-managed state

```python
first = await client.responses.create(model="gpt-5.5", input="tell me a joke")
second = await client.responses.create(
    model="gpt-5.5",
    previous_response_id=first.id,
    input=[{"role": "user", "content": "explain why this is funny."}],
)
```

- `previous_response_id` chains onto a stored prior response, so you only send the new turn.
- `client.conversations.create()` gives a `conv_...` id you pass as `conversation=` for a persistent thread.
- Instructions from previous turns are **not** carried over with `previous_response_id`.
- Trade-off: the history lives on OpenAI, so it can't be replayed to a different provider.

---

## 4A. Request parameters reference

### Chat Completions — `client.chat.completions.create(...)`

| Param | Type / values | Notes |
|---|---|---|
| `model` | str | **Required.** e.g. `"gpt-5.5"` |
| `messages` | list of message dicts | **Required.** Full history, oldest first (see 4B) |
| `max_completion_tokens` | int | Cap on generated tokens, **including reasoning tokens**. Use this. |
| `max_tokens` | int | **Deprecated.** Not compatible with reasoning models. Only for old non-reasoning models. |
| `reasoning_effort` | `"none"`, `"minimal"`, `"low"`, `"medium"`, `"high"`, `"xhigh"` | Reasoning models only; allowed values differ per model |
| `verbosity` | `"low"`, `"medium"`, `"high"` | GPT-5 family; controls answer length/detail |
| `temperature` | float 0–2 | Randomness. **Not supported on reasoning models** |
| `top_p` | float 0–1 | Nucleus sampling. Not supported on reasoning models |
| `presence_penalty`, `frequency_penalty` | float -2 to 2 | Not supported on reasoning models |
| `stop` | str or list (up to 4) | Stop sequences; not on newer reasoning models |
| `n` | int | Number of alternative replies (you pay for all) |
| `seed` | int | Best-effort determinism |
| `stream` | bool | SSE streaming |
| `stream_options` | `{"include_usage": True}` | Get `usage` on the final chunk when streaming |
| `response_format` | `{"type": "json_object"}` or `{"type": "json_schema", ...}` | JSON / structured output |
| `tools`, `tool_choice`, `parallel_tool_calls` | — | Function calling |
| `metadata` | dict[str, str] | Tags for your own tracking |
| `store` | bool | Store for evals/distillation on OpenAI's side |

### Responses — `client.responses.create(...)`

| Param | Type / values | Notes |
|---|---|---|
| `model` | str | **Required** |
| `input` | str **or** list of items | A single prompt, or the full history list (see 4B) |
| `instructions` | str | System-level prompt; **only applies to this request** |
| `max_output_tokens` | int | Cap on generated tokens (visible + reasoning) |
| `reasoning` | `{"effort": "low" \| "medium" \| ...}` | Reasoning models |
| `text` | `{"verbosity": "low", "format": {...}}` | Verbosity and structured output live here |
| `temperature`, `top_p` | float | Non-reasoning models only |
| `stream` | bool | Streams typed events |
| `store` | bool (default `true`) | `true` keeps the response on OpenAI for 30 days; set `false` if you manage history yourself |
| `previous_response_id` | str | Chain onto a stored response (server-side history) |
| `conversation` | str (`conv_...`) | Durable server-side conversation object |
| `truncation` | `"auto"` / `"disabled"` | What to do when input exceeds the context window |
| `tools`, `tool_choice` | — | Function calling and built-in tools |
| `metadata` | dict | Your tags |

Not in Responses: `n` (multiple completions).

### Parameter gotchas

- **Output cap vs reasoning.** On reasoning models the cap covers hidden reasoning too. Set it too low and the model can spend it all thinking and return an **empty string**:
  - Chat Completions → `finish_reason == "length"` with empty `content`
  - Responses → `status == "incomplete"`, check `incomplete_details.reason`
  Treat both as a distinct error, not a successful empty reply.
- **Sampling params break on reasoning models.** Sending `temperature` to a model that doesn't support it returns a 400. A gateway serving many models needs per-model knowledge of which params are allowed.
- **Omit, don't send `None`.** Build the kwargs dict and only add keys that are set:

```python
params = {"model": model_id, "messages": messages}
if max_out is not None:
    params["max_completion_tokens"] = max_out
if model_supports_temperature and temperature is not None:
    params["temperature"] = temperature

resp = await client.chat.completions.create(**params)
```

- Provider- or model-specific params the SDK doesn't type yet: `extra_body={...}`.
- Context window = input + output + reasoning tokens. Check each model's limits on its model page.

---

## 4B. Sending previous messages — in detail

### Message shape

Minimum: `{"role": "...", "content": "..."}`.

| Role | Who writes it | Use |
|---|---|---|
| `system` / `developer` | You (the server) | Behaviour rules. `developer` is the newer name on OpenAI |
| `user` | End user | Their turns |
| `assistant` | The model | Its previous replies, replayed back |
| `tool` (Chat Completions) | You | Result of a function call; needs `tool_call_id` |

`content` can be a plain string or a list of parts:

```python
# Chat Completions multimodal user message
{"role": "user", "content": [
    {"type": "text", "text": "What's in this image?"},
    {"type": "image_url", "image_url": {"url": "https://..."}},
]}

# Responses API equivalent
{"role": "user", "content": [
    {"type": "input_text", "text": "What's in this image?"},
    {"type": "input_image", "image_url": "https://..."},
]}
```

For text-only chat, plain strings are simplest and portable.

### Ordering rules

1. System/developer prompt first (or use `instructions=` in Responses).
2. Then prior turns in **chronological order** (oldest → newest).
3. The **new user message last**.

```python
messages = [
    {"role": "developer", "content": SYSTEM_PROMPT},
    *prior_turns,                                   # [{"role": "user", ...}, {"role": "assistant", ...}, ...]
    {"role": "user", "content": new_user_text},
]
```

### The turn loop

1. Load prior turns for the conversation (e.g. from DB, ordered by `created_at`).
2. Build `messages` = system + prior turns + new user message.
3. Call the model.
4. Take the reply and append it as an `assistant` message.
5. Persist the new user message and the assistant message.

What to append after each call:

| API | Portable (plain text) | OpenAI-native (keeps reasoning items) |
|---|---|---|
| Chat Completions | `{"role": "assistant", "content": resp.choices[0].message.content}` | same |
| Responses | `{"role": "assistant", "content": resp.output_text}` | `history += resp.output` |

### Converting stored rows to messages

If rows have `role` and `content` columns, it's a straight map:

```python
prior_turns = [{"role": r.role, "content": r.content} for r in rows]
```

### Trimming history

Every turn resends everything, and **you're billed for all of it as input tokens every time** — even with `previous_response_id`. Long chats get expensive and eventually overflow the context window.

Common policies:
- Keep the system prompt + last N messages.
- Keep a token budget: walk backwards from the newest message, adding until the budget is hit (estimate with `tiktoken`, reconcile with real `usage`).
- Summarise old turns into one message once the chat passes a threshold.
- Responses API only: `truncation="auto"` lets OpenAI drop old items for you.

Rules when trimming:
- Never drop the system prompt.
- Drop from the oldest end.
- Keep tool-call pairs together: an `assistant` message with `tool_calls` must be followed by its `tool` result messages. Removing one without the other → 400.
- The history should still end with the new `user` message.

### Gateway-specific cautions

- **Don't trust client-supplied roles blindly.** If users can send `system`/`developer` messages through your API, they can override your server prompt. Decide which roles an API key may send.
- **Cap message count and size** per request before calling the provider, so one request can't burn a daily quota.
- **Switching models mid-chat** works fine with plain-text history. Other providers have their own rules (e.g. Anthropic takes the system prompt as a separate param), so convert per provider rather than sending OpenAI's list as-is.

---

## 5. Streaming

### Chat Completions

```python
stream = await client.chat.completions.create(
    model="gpt-5.5",
    messages=history,
    stream=True,
    stream_options={"include_usage": True},  # final chunk carries usage
)

parts = []
async for chunk in stream:
    if chunk.usage:                 # last chunk, empty choices
        usage = chunk.usage
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta.content
    if delta:
        parts.append(delta)

full_text = "".join(parts)          # save this as the assistant message
```

### Responses

```python
stream = await client.responses.create(model="gpt-5.5", input=history, stream=True)

async for event in stream:
    if event.type == "response.output_text.delta":
        ...  # event.delta is a text piece
    elif event.type == "response.completed":
        final = event.response      # has output_text and usage
```

Streaming notes:
- Accumulate the full text yourself; you need it to append to history.
- If the client disconnects mid-stream, decide whether the partial reply gets saved (see design notes).
- To forward to your own clients from FastAPI, wrap the `async for` in a `StreamingResponse` (SSE).

---

## 6. Errors, retries, timeouts

All errors inherit from `openai.APIError`.

| Status | Exception |
|---|---|
| 400 | `BadRequestError` (e.g. bad role, context too long) |
| 401 | `AuthenticationError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` (e.g. unknown model) |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitError` |
| >=500 | `InternalServerError` |
| — | `APIConnectionError` (network), `APITimeoutError` (timeout) |

```python
import openai

try:
    resp = await client.chat.completions.create(model="gpt-5.5", messages=history)
except openai.RateLimitError:
    ...  # back off / return 429 to your caller
except openai.APIStatusError as e:
    log(e.status_code, e.request_id)
except openai.APIConnectionError as e:
    log(e.__cause__)
```

Retries (built-in):
- Default **2 retries** with exponential backoff on connection errors, 408, 409, 429, >=500.
- `AsyncOpenAI(max_retries=0)` or per call: `client.with_options(max_retries=5).chat.completions.create(...)`.

Timeouts:
- Default **10 minutes** — far too long for a gateway. Set something explicit:
  `AsyncOpenAI(timeout=httpx.Timeout(60.0, connect=5.0))`, or per call with `with_options(timeout=...)`.
- Timed-out requests are retried too, so worst case ≈ timeout × (retries + 1).

---

## 7. Other handy bits

- `resp.to_dict()` / `resp.to_json()` — responses are Pydantic models; good for logging raw payloads.
- `client.chat.completions.with_raw_response.create(...)` → access headers (e.g. rate-limit headers), then `.parse()` for the normal object.
- `base_url=` (or `OPENAI_BASE_URL`) points the same SDK at any OpenAI-compatible server.
- `extra_body=`, `extra_headers=` for params the SDK doesn't type yet.
- `OPENAI_LOG=debug` env var for request logging.
- Concurrency: fan out with `asyncio.gather(...)` on the shared client; limit fan-out with an `asyncio.Semaphore` to respect rate limits.

---

## 8. Design decisions for SentryKey's conversation memory

These are trade-offs to decide, not a finished implementation.

**Where history lives.**
Memory must survive model switches across OpenAI, Anthropic and Google, so the source of truth should be your own Postgres `messages` table, not `previous_response_id` / Conversations. Server-side state is OpenAI-only and invisible to the other providers.

**What shape to store.**
Store a provider-neutral row per message: `conversation_id`, `role` (`system`/`user`/`assistant`), `content` text, `model` that produced it, token counts, `created_at`. Then write one small adapter per provider that turns rows into that provider's request format. Chat Completions' `messages` shape is the closest thing to a common denominator. Cost of this choice: you drop OpenAI's encrypted reasoning items, so reasoning models don't see prior reasoning. Usually acceptable for a gateway.

**Chat Completions vs Responses for the OpenAI adapter.**
Chat Completions maps 1:1 to your stored rows and matches the OpenAI-compatible API you expose. Responses is where OpenAI is putting new features. Starting with Chat Completions keeps the adapter trivial; you can swap later without touching the table.

**System prompt.**
Store it once per conversation (or per tier), and inject it at request time rather than as a message row. Anthropic takes it as a separate `system` param, so keeping it out of the message list simplifies adapters.

**Context window / quota.**
History grows every turn and every turn re-bills all input tokens against the daily quota. Decide on a truncation policy (last N messages, or a token budget per model) before it bites. Count against quota using the `usage` returned by the provider, not your own estimate.

**When to write rows.**
Options: write the user message before calling the model and the assistant message after success; or write both in one transaction after success. The first keeps a record of failed attempts; the second avoids orphan user messages. For streaming, also decide whether a disconnected, partial reply is saved.

**Client and failure behaviour.**
One `AsyncOpenAI` per process in `lifespan`. Set explicit timeout and `max_retries` so a slow provider can't hold a request for 30 minutes. Map provider `RateLimitError` / `APIStatusError` to your own gateway error responses instead of leaking them.