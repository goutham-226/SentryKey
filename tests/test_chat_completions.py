# tests/test_chat_completions.py

# Test POST /v1/chat/completions with a fake OpenAI provider -> no test calls a real provider.

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Conversations, Messages, UsageRecords
from app.services import provider_service
from app.services.provider_data import provider_response

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
Return a function that sends a chat request
with a Basic tier key for gpt-5.6-luna.
"""
@pytest.fixture
async def send_chat(client, subscribed_api_key):
    key = (await subscribed_api_key('Basic'))['api_key']

    async def _send_chat(conversation_id: int | None = None):
        request = {'prompt': 'hi', 'model': 'gpt-5.6-luna', 'max_tokens': 100, 'conversation_id': conversation_id}
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
