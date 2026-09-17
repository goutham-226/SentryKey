# Gemini + Claude (async Python) — Dev Notes

Companion to the OpenAI notes. Same scope: calling models asynchronously, request parameters, and feeding back previous messages.
Sources: `googleapis/python-genai` docs, Claude Messages API reference and Python SDK docs.

---

# Part 1 — Google Gemini (`google-genai`)

## 1.1 Install and client

```bash
pip install google-genai
```

```python
from google import genai
from google.genai import types

client = genai.Client()              # reads GEMINI_API_KEY (or GOOGLE_API_KEY)
```

- `client.aio.*` mirrors every sync method: `client.aio.models.generate_content` is the async version.
- Vertex AI variant: `genai.Client(vertexai=True, project=..., location=...)` — different auth, same call shape.
- The SDK defaults to beta endpoints; pin stable with `http_options=types.HttpOptions(api_version="v1")`.
- Async client can be used as a context manager: `async with genai.Client().aio as aclient:` — closes the underlying HTTP client on exit. In FastAPI, build it once in `lifespan`.

```python
resp = await client.aio.models.generate_content(
    model="gemini-3.8-flash",
    contents="Why is the sky blue?",
)
print(resp.text)
```

## 1.2 Request parameters

Everything except `model` and `contents` goes inside `config=types.GenerateContentConfig(...)` (a dict works too).

| Param | Notes |
|---|---|
| `model` | top-level, required |
| `contents` | top-level, required — string, `Part`, or a list of `Content` items (the history) |
| `system_instruction` | the system prompt; lives in config, **not** in `contents` |
| `max_output_tokens` | cap on generated tokens |
| `temperature` | randomness |
| `top_p`, `top_k` | sampling |
| `candidate_count` | number of candidate answers |
| `stop_sequences` | list of strings |
| `seed` | best-effort determinism |
| `presence_penalty`, `frequency_penalty` | repetition control |
| `safety_settings` | `[types.SafetySetting(category=..., threshold=...)]` — Gemini blocks content by default; this is the knob |
| `response_mime_type` / `response_schema` | JSON / structured output |
| `response_modalities` | e.g. `["TEXT"]` |
| `thinking_config` | thinking budget / whether thoughts are returned, on thinking-capable models |
| `tools`, `tool_config` | function calling |

```python
resp = await client.aio.models.generate_content(
    model="gemini-3.8-flash",
    contents=history,
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        max_output_tokens=1024,
        temperature=0.7,
    ),
)
```

Response fields:
- `resp.text` — convenience accessor for the concatenated text. It can be `None` (blocked, or the model returned only non-text parts), so check before using.
- `resp.candidates[0].content.parts` — the raw parts.
- `resp.candidates[0].finish_reason` — `STOP`, `MAX_TOKENS`, `SAFETY`, ...
- `resp.usage_metadata` — `prompt_token_count`, `candidates_token_count`, `total_token_count` (plus a thoughts count on thinking models).
- `resp.prompt_feedback` — why a prompt was blocked, if it was.

## 1.3 History: the `contents` format

Gemini's shape differs from OpenAI's in three ways that matter:

1. The assistant role is called **`model`**, not `assistant`.
2. Text lives in a **`parts`** list, not a `content` string.
3. The system prompt is a **config field**, not a message.

```python
history = [
    {"role": "user",  "parts": [{"text": "knock knock."}]},
    {"role": "model", "parts": [{"text": "Who's there?"}]},
    {"role": "user",  "parts": [{"text": "Orange."}]},
]

resp = await client.aio.models.generate_content(
    model="gemini-3.8-flash",
    contents=history,
    config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
)

history.append({"role": "model", "parts": [{"text": resp.text}]})
```

Typed equivalent (same thing, validated):

```python
types.Content(role="user", parts=[types.Part.from_text(text="Orange.")])
```

Converting your stored rows:

```python
ROLE_MAP = {"user": "user", "assistant": "model"}

contents = [
    {"role": ROLE_MAP[r.role], "parts": [{"text": r.content}]}
    for r in rows if r.role != "system"          # system goes to config
]
```

### Chat helper (optional)

```python
chat = client.aio.chats.create(model="gemini-3.8-flash", history=history)
resp = await chat.send_message("Orange.")
```

It keeps history in memory for you. For a gateway with Postgres as the source of truth, the stateless `generate_content` call is the better fit — state in memory doesn't survive across workers or requests.

### Gotchas

- History must start with a `user` turn and alternate.
- A `SAFETY` finish reason means no usable text. Don't append an empty assistant turn to history, or the next request carries a broken turn.
- Gemini also exposes an **OpenAI-compatible endpoint**. Pointing the OpenAI SDK at it with `base_url` is the shortest path, but you lose Gemini-specific params (safety settings, thinking config), and the compatibility layer lags the native API. For a gateway that advertises "multiple providers", prefer the native SDK per provider.

---

# Part 2 — Anthropic Claude (`anthropic`)

## 2.1 Install and client

```bash
pip install anthropic
pip install "anthropic[aiohttp]"    # optional aiohttp backend
```

```python
from anthropic import AsyncAnthropic

client = AsyncAnthropic()           # reads ANTHROPIC_API_KEY
```

Same ergonomics as the OpenAI SDK: import `AsyncAnthropic` instead of `Anthropic` and `await` each call; everything else is identical. One client per process, closed on shutdown.

```python
msg = await client.messages.create(
    model="claude-sonnet-5",
    max_tokens=1024,
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": "Hello, Claude"}],
)
```

## 2.2 Request parameters

| Param | Notes |
|---|---|
| `model` | **Required** |
| `max_tokens` | **Required** — unlike OpenAI, there's no default. Every call must set it |
| `messages` | **Required** — history, `user`/`assistant` only |
| `system` | System prompt as a **top-level param**. There is no `system` role in `messages`; sending one is a 400 |
| `temperature` | 0–1 |
| `top_p`, `top_k` | sampling |
| `stop_sequences` | list of strings |
| `stream` | bool |
| `thinking` | extended thinking config; the thinking budget counts toward `max_tokens` (minimum budget 1,024) |
| `tools`, `tool_choice` | function calling |
| `metadata` | e.g. an end-user id |
| `context_management` | server-side context control, e.g. clearing old tool results |
| `cache_control` (on blocks) | prompt caching — marks a prefix as cacheable |

Response fields:
- `msg.content` — a **list of content blocks**, not a string. Text is in blocks with `type == "text"`; thinking models also return `thinking` blocks.
- `msg.stop_reason` — `end_turn`, `max_tokens`, `stop_sequence`, `tool_use`.
- `msg.usage.input_tokens` / `output_tokens` (extended-thinking tokens are folded into output tokens), plus cache read/write counts when caching is on.
- `msg.id`, `msg.model`.

Extracting text:

```python
text = "".join(b.text for b in msg.content if b.type == "text")
```

## 2.3 History: the `messages` format

Closest to OpenAI's shape — `{"role": "user" | "assistant", "content": ...}` — with these rules:

- Models are trained on alternating user and assistant turns, and consecutive same-role turns in a request get merged into one turn.
- The system prompt goes in the `system` param, never as a message.
- `content` is either a string or a list of typed blocks (`{"type": "text", "text": ...}`, images, tool results). A plain string is shorthand for one text block.
- If the last message is an `assistant` message, the model **continues from it** instead of starting a new turn. Useful for prefilling; a bug if you accidentally leave a trailing assistant message in your history.
- Hard limit of 100,000 messages per request (you'll hit the context window long before that).

```python
messages = [
    {"role": "user", "content": "Hello there."},
    {"role": "assistant", "content": "Hi, I'm Claude. How can I help you?"},
    {"role": "user", "content": new_user_text},
]

msg = await client.messages.create(
    model="claude-sonnet-5",
    max_tokens=1024,
    system=SYSTEM_PROMPT,
    messages=messages,
)

messages.append({"role": "assistant", "content": text_of(msg)})
```

Converting your stored rows:

```python
messages = [
    {"role": r.role, "content": r.content}
    for r in rows if r.role in ("user", "assistant")
]
```

### Gotchas

- Forgetting `max_tokens` is a 400, not a default.
- With extended thinking and tool use, thinking blocks must be passed back in later turns to preserve the reasoning chain. If you store plain text only, keep thinking off for those models, or store the raw blocks as JSON.
- Errors and retries mirror the OpenAI SDK (`anthropic.RateLimitError`, `APIStatusError`, `APIConnectionError`, built-in retries, configurable `timeout`).

---

# Part 3 — Cross-provider mapping (for the gateway adapters)

| Concept | OpenAI (Chat Completions) | Gemini | Claude |
|---|---|---|---|
| Call | `chat.completions.create` | `aio.models.generate_content` | `messages.create` |
| History param | `messages` | `contents` | `messages` |
| Assistant role name | `assistant` | `model` | `assistant` |
| Text field | `content` (str or parts) | `parts: [{"text": ...}]` | `content` (str or blocks) |
| System prompt | a message (`system`/`developer`) | `config.system_instruction` | top-level `system` |
| Output cap | `max_completion_tokens` | `config.max_output_tokens` | `max_tokens` (**required**) |
| Other params live | top level | inside `config` | top level |
| Text out | `choices[0].message.content` | `resp.text` | `[b.text for b in msg.content if b.type == "text"]` |
| Usage | `usage.prompt_tokens` / `completion_tokens` | `usage_metadata.prompt_token_count` / `candidates_token_count` | `usage.input_tokens` / `output_tokens` |
| Why it stopped | `finish_reason` | `finish_reason` + `prompt_feedback` | `stop_reason` |

## Design notes for SentryKey

**Canonical internal format.** Pick one neutral shape — `{"role": "system" | "user" | "assistant", "content": "<text>"}` rows in Postgres — and write a small adapter per provider that does three jobs: pull the system prompt out, rename roles, and wrap text in whatever container that provider wants. All three providers accept plain text history, so this stays lossless for text chat. It stops being lossless for reasoning traces and tool calls — decide whether your MVP needs those before designing around them.

**Adapter interface.** Something like `async def complete(model_row, system, messages, params) -> Completion`, where `Completion` carries text, input/output tokens, stop reason and the raw response for logging. Keeping the return type uniform is what lets your quota metering and logging stay provider-agnostic.

**Parameter translation.** Your public API exposes one set of knobs (OpenAI-shaped, since that's what clients expect). Each adapter maps them: `max_tokens` → `max_completion_tokens` / `max_output_tokens` / `max_tokens`. Store per-model capability flags in the models table (supports temperature? requires max_tokens? supports thinking?) so you can reject or drop unsupported params before the provider 400s.

**Errors.** Each SDK raises its own exception types with the same rough meanings. Map them to a single internal error enum (auth, rate limit, bad request, overloaded, timeout, network) in the adapter, so your FastAPI error handlers don't grow a branch per provider.

**Token accounting.** The three report usage under different names and count reasoning differently. Normalise to `input_tokens` / `output_tokens` at the adapter boundary and always meter against what the provider reported, not an estimate.

**Model switching mid-conversation.** This works because history is plain text — but the system prompt and the params move differently per provider, and each model has its own context window. Trim against the *target* model's window at request time, not once when the conversation was created.

**Clients.** Three long-lived clients (`AsyncOpenAI`, `genai.Client`, `AsyncAnthropic`) created in `lifespan` and stored on `app.state`. Each keeps its own connection pool; creating them per request is the classic way to make a gateway slow.
