# tests/test_chat_completions.py

# Test POST /v1/chat/completions with a fake OpenAI provider -> no test calls a real provider.

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Conversations, MessageTokenCounts, Messages, Models, UsageRecords
from app.services import anthropic_ai, provider_service
from app.services.provider_data import provider_response
from tests.test_providers import fake_anthropic_client

"""
Fake get_openai_response replacements.

completed -> the model answered, messages are saved.
failed -> the model failed before generating (e.g. a rate limit), nothing is billed.
"""
async def completed_response(payload, context, history_tokens, prompt_tokens):
    return provider_response(
        response='hello there',
        prompt_tokens=prompt_tokens,
        completion_tokens=5,
        context_tokens=history_tokens,
        status_code=200,
        status='Completed',
        started_generation=True,
        billable=True,
        response_tokens=5,
    )

async def failed_response(payload, context, history_tokens, prompt_tokens):
    return provider_response(
        response='Sorry model is not available at the moment please try again later or use a different model',
        prompt_tokens=0,
        completion_tokens=0,
        context_tokens=0,
        status_code=429,
        status='Failed',
        started_generation=False,
        billable=False,
        response_tokens=0,
    )

"""
truncated -> thinking used most of max_tokens, the reply was cut off (or never started).
"""
def truncated_response(text: str):
    async def _truncated_response(payload, context, history_tokens, prompt_tokens):
        return provider_response(
            response=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=100,
            context_tokens=history_tokens,
            status_code=200,
            status='Truncated',
            started_generation=True,
            billable=True,
            response_tokens=len(text) // 4,
        )
    return _truncated_response

"""
Return a function that sends a chat request
with a Basic tier key for gpt-5.6-luna.
"""
@pytest.fixture
async def send_chat(client, subscribed_api_key):
    key = (await subscribed_api_key('Basic'))['api_key']

    async def _send_chat(conversation_id: int | None = None, model: str = 'gpt-5.6-luna', max_tokens: int = 100):
        request = {'prompt': 'hi', 'model': model, 'max_tokens': max_tokens, 'conversation_id': conversation_id}
        return await client.post('/v1/chat/completions', json=request, headers={'Authorization': f'Bearer {key}'})
    return _send_chat

async def count_rows(model) -> int:
    async with SessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()

"""
Test if a first turn that fails before generating
leaves no conversation behind, returns conversation_id null,
and settles its usage record to 0 tokens with no conversation.
"""
async def test_failed_first_turn_leaves_no_conversation(send_chat, monkeypatch):
    monkeypatch.setattr(provider_service, 'get_openai_response', failed_response)

    response = await send_chat()

    assert response.status_code == 200
    assert response.json()['conversation_id'] is None
    assert await count_rows(Conversations) == 0
    assert await count_rows(Messages) == 0

    async with SessionLocal() as db:
        row = (await db.execute(select(UsageRecords))).scalar_one()
    assert row.status == 'Failed'
    assert row.conversation_id is None
    assert (row.prompt_tokens, row.completion_tokens, row.context_tokens) == (0, 0, 0)

"""
Test if a failed turn on an existing conversation
keeps the conversation and its earlier messages.
"""
async def test_failed_turn_keeps_existing_conversation(send_chat, monkeypatch):
    monkeypatch.setattr(provider_service, 'get_openai_response', completed_response)
    conversation_id = (await send_chat()).json()['conversation_id']

    monkeypatch.setattr(provider_service, 'get_openai_response', failed_response)
    response = await send_chat(conversation_id=conversation_id)

    assert response.status_code == 200
    assert response.json()['conversation_id'] == conversation_id
    assert await count_rows(Conversations) == 1
    assert await count_rows(Messages) == 2

"""
Test if a successful first turn keeps its conversation
with the user and assistant messages.
"""
async def test_completed_first_turn_keeps_conversation(send_chat, monkeypatch):
    monkeypatch.setattr(provider_service, 'get_openai_response', completed_response)

    response = await send_chat()

    assert response.status_code == 200
    body = response.json()
    assert body['conversation_id'] is not None
    assert body['output'] == 'hello there'
    assert await count_rows(Conversations) == 1
    async with SessionLocal() as db:
        roles = (await db.execute(select(Messages.role).order_by(Messages.id))).scalars().all()
    assert roles == ['user', 'assistant']

"""
Test if a truncated reply with no visible text
saves no messages and deletes the conversation it created,
but is still billed in full and returns error_detail.
"""
async def test_empty_truncated_reply_is_billed_but_not_saved(send_chat, monkeypatch):
    monkeypatch.setattr(provider_service, 'get_openai_response', truncated_response(''))

    response = await send_chat()

    assert response.status_code == 200
    body = response.json()
    assert body['conversation_id'] is None
    assert body['error_detail'] == provider_service.TRUNCATED_DETAIL
    assert await count_rows(Conversations) == 0
    assert await count_rows(Messages) == 0

    async with SessionLocal() as db:
        row = (await db.execute(select(UsageRecords))).scalar_one()
    assert row.status == 'Truncated'
    assert row.completion_tokens == 100
    assert row.conversation_id is None

"""
Test if a truncated reply with visible text
is saved like any other turn and returns error_detail.
"""
async def test_partial_truncated_reply_is_saved(send_chat, monkeypatch):
    monkeypatch.setattr(provider_service, 'get_openai_response', truncated_response('The answer is'))

    response = await send_chat()

    assert response.status_code == 200
    body = response.json()
    assert body['conversation_id'] is not None
    assert body['output'] == 'The answer is'
    assert body['error_detail'] == provider_service.TRUNCATED_DETAIL
    assert await count_rows(Messages) == 2

"""
Test if an empty reply on an existing conversation
keeps the conversation and adds no messages to it.
"""
async def test_empty_reply_keeps_existing_conversation(send_chat, monkeypatch):
    monkeypatch.setattr(provider_service, 'get_openai_response', completed_response)
    conversation_id = (await send_chat()).json()['conversation_id']

    monkeypatch.setattr(provider_service, 'get_openai_response', truncated_response(''))
    response = await send_chat(conversation_id=conversation_id)

    assert response.json()['conversation_id'] == conversation_id
    assert await count_rows(Conversations) == 1
    assert await count_rows(Messages) == 2

"""
Test if a completed reply returns no error_detail.
"""
async def test_completed_reply_has_no_error_detail(send_chat, monkeypatch):
    monkeypatch.setattr(provider_service, 'get_openai_response', completed_response)

    response = await send_chat()

    assert response.json()['error_detail'] is None

"""
Fake provider that records the max_tokens it was sent.
"""
def recording_response(sent: list[int]):
    async def _recording_response(payload, context, history_tokens, prompt_tokens):
        sent.append(payload.max_tokens)
        return await completed_response(payload, context, history_tokens, prompt_tokens)
    return _recording_response

async def fake_anthropic_tokens(text, model, role):
    return 1

"""
Test if max_tokens above the model's output limit is capped to it
before reserving -> claude-haiku-4-5 allows 64,000, below the 100,000 daily quota.
"""
async def test_max_tokens_capped_to_model_limit(send_chat, monkeypatch):
    sent: list[int] = []
    monkeypatch.setattr(provider_service, 'get_anthropic_tokens', fake_anthropic_tokens)
    monkeypatch.setattr(provider_service, 'get_anthropic_response', recording_response(sent))

    response = await send_chat(model='claude-haiku-4-5', max_tokens=90_000)

    assert response.status_code == 200
    assert sent == [64_000]

"""
Test if max_tokens below the model's output limit is left alone
-> only the quota lowers it.
"""
async def test_max_tokens_under_model_limit_is_kept(send_chat, monkeypatch):
    sent: list[int] = []
    monkeypatch.setattr(provider_service, 'get_openai_response', recording_response(sent))

    response = await send_chat(model='gpt-5.6-luna', max_tokens=90_000)

    assert response.status_code == 200
    assert sent == [90_000]

"""
Test if every seeded model has an output limit.
"""
async def test_every_model_has_output_limit():
    async with SessionLocal() as db:
        limits = dict((await db.execute(select(Models.model_id, Models.max_output_tokens))).all())

    assert len(limits) == 9
    assert all(limit is not None for limit in limits.values())
    assert limits['claude-haiku-4-5'] == 64_000

"""
Test if a Claude turn bills and stores the prompt's own count,
without the system prompt -> the fake client reports input_tokens=12,
the pre-call count of the prompt is 3.
"""
async def test_claude_turn_excludes_system_prompt(send_chat, monkeypatch):
    async def three_tokens(text, model, role):
        return 3
    monkeypatch.setattr(provider_service, 'get_anthropic_tokens', three_tokens)
    monkeypatch.setattr(anthropic_ai, 'client', fake_anthropic_client('end_turn'))

    response = await send_chat(model='claude-haiku-4-5')

    assert response.status_code == 200
    assert response.json()['prompt_tokens'] == 3
    async with SessionLocal() as db:
        user_tokens = (await db.execute(select(Messages.token_count).where(Messages.role == 'user'))).scalar_one()
        billed = (await db.execute(select(UsageRecords.prompt_tokens))).scalar_one()
    assert user_tokens == 3
    assert billed == 3

"""
History recount after a model switch.

turn 1 on gpt-5.6-luna stores user 'hi' (tiktoken: 1) and assistant 'hello there' (5, from the fake).
then the conversation moves to claude-haiku-4-5, whose fake counter returns claude_count for every text.
"""
def fake_claude_counter(calls: list[str], claude_count: int, fail_on: str | None = None):
    async def _count(text, model, role):
        calls.append(text)
        if text == fail_on:
            raise RuntimeError('count_tokens failed')
        return claude_count
    return _count

async def start_on_gpt_then_use_claude(send_chat, monkeypatch, calls: list[str], claude_count: int, fail_on: str | None = None) -> int:
    monkeypatch.setattr(provider_service, 'get_openai_response', completed_response)
    conversation_id = (await send_chat()).json()['conversation_id']

    monkeypatch.setattr(provider_service, 'get_anthropic_tokens', fake_claude_counter(calls, claude_count, fail_on))
    monkeypatch.setattr(provider_service, 'get_anthropic_response', completed_response)
    response = await send_chat(conversation_id=conversation_id, model='claude-haiku-4-5')
    assert response.status_code == 200
    return conversation_id

async def last_context_tokens() -> int:
    async with SessionLocal() as db:
        return (await db.execute(select(UsageRecords.context_tokens).order_by(UsageRecords.id.desc()).limit(1))).scalar_one()

"""
Test if GPT history is recounted with Claude, billed at the larger count,
and saved -> prompt + 2 history messages are counted.
"""
async def test_switch_recounts_history_and_bills_larger_count(send_chat, monkeypatch):
    calls: list[str] = []
    await start_on_gpt_then_use_claude(send_chat, monkeypatch, calls, claude_count=10)

    assert sorted(calls) == ['hello there', 'hi', 'hi']
    # max(1, 10) + max(5, 10)
    assert await last_context_tokens() == 20
    async with SessionLocal() as db:
        saved = (await db.execute(select(MessageTokenCounts.model, MessageTokenCounts.token_count))).all()
    assert sorted(saved) == [('claude-haiku-4-5', 10), ('claude-haiku-4-5', 10)]

"""
Test if the next Claude request reuses the saved counts
-> only the new prompt is counted.
"""
async def test_saved_counts_are_reused(send_chat, monkeypatch):
    calls: list[str] = []
    conversation_id = await start_on_gpt_then_use_claude(send_chat, monkeypatch, calls, claude_count=10)

    calls.clear()
    await send_chat(conversation_id=conversation_id, model='claude-haiku-4-5')

    assert calls == ['hi']
    # gpt messages from the saved counts (10 + 10), claude messages from their own counts (user 10, assistant 5).
    assert await last_context_tokens() == 35

"""
Test if a recount smaller than the stored count
bills the stored count -> history is never under-billed.
"""
async def test_smaller_recount_bills_stored_count(send_chat, monkeypatch):
    await start_on_gpt_then_use_claude(send_chat, monkeypatch, [], claude_count=0)

    # max(1, 0) + max(5, 0)
    assert await last_context_tokens() == 6

"""
Test if a failed recount falls back to the stored count
and is not saved, while the other message's recount is.
"""
async def test_failed_recount_uses_stored_count(send_chat, monkeypatch):
    await start_on_gpt_then_use_claude(send_chat, monkeypatch, [], claude_count=10, fail_on='hello there')

    # max(1, 10) + stored 5
    assert await last_context_tokens() == 15
    assert await count_rows(MessageTokenCounts) == 1

"""
Test if history from the same model is never recounted
-> only the new prompt is counted.
"""
async def test_same_model_history_is_not_recounted(send_chat, monkeypatch):
    calls: list[str] = []

    async def recording_openai_tokens(text):
        calls.append(text)
        return 1
    monkeypatch.setattr(provider_service, 'get_openai_tokens', recording_openai_tokens)
    monkeypatch.setattr(provider_service, 'get_openai_response', completed_response)
    conversation_id = (await send_chat()).json()['conversation_id']

    calls.clear()
    await send_chat(conversation_id=conversation_id)

    assert calls == ['hi']
    assert await count_rows(MessageTokenCounts) == 0
