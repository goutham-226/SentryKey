# tests/test_providers.py

# Test how each provider module reports a reply that hit max_tokens.
# every SDK client is replaced with a fake stream -> no test calls a real provider.

from types import SimpleNamespace as NS

import pytest

from app.schemas import ChatRequest
from app.services import anthropic_ai, google_ai, open_ai


def make_payload(model: str) -> ChatRequest:
    return ChatRequest(prompt='hi', model=model, max_tokens=50)

async def stream_of(items):
    for item in items:
        yield item

"""
OpenAI: a text chunk, a finish chunk, then the usage chunk (stream_options include_usage).
"""
def fake_openai_client(finish_reason: str):
    chunks = [
        NS(usage=None, choices=[NS(delta=NS(content='Hello'), finish_reason=None)]),
        NS(usage=None, choices=[NS(delta=NS(content=None), finish_reason=finish_reason)]),
        NS(usage=NS(prompt_tokens=10, completion_tokens=50, completion_tokens_details=NS(reasoning_tokens=45)), choices=[]),
    ]

    async def create(**kwargs):
        return stream_of(chunks)
    return NS(chat=NS(completions=NS(create=create)))

@pytest.mark.parametrize('finish_reason, status', [('length', 'Truncated'), ('stop', 'Completed')])
async def test_openai_status(monkeypatch, finish_reason, status):
    monkeypatch.setattr(open_ai, 'client', fake_openai_client(finish_reason))

    response = await open_ai.get_openai_response(payload=make_payload('gpt-5.6-luna'), context=[], history_tokens=0, prompt_tokens=2)

    assert response.status == status
    assert response.status_code == 200
    assert response.billable is True
    assert response.response == 'Hello'
    assert (response.completion_tokens, response.response_tokens) == (50, 5)

"""
Anthropic: message_start, a text delta, then message_delta with the stop_reason.
"""
class FakeAnthropicStream:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return stream_of(self.events)

    async def __aexit__(self, *exc):
        return False

def fake_anthropic_client(stop_reason: str):
    events = [
        NS(type='message_start', message=NS(usage=NS(input_tokens=12))),
        NS(type='content_block_delta', delta=NS(type='text_delta', text='Hello')),
        NS(type='message_delta', delta=NS(stop_reason=stop_reason),
           usage=NS(output_tokens=50, output_tokens_details=NS(thinking_tokens=45))),
    ]
    return NS(messages=NS(stream=lambda **kwargs: FakeAnthropicStream(events)))

@pytest.mark.parametrize('stop_reason, status', [('max_tokens', 'Truncated'), ('end_turn', 'Completed')])
async def test_anthropic_status(monkeypatch, stop_reason, status):
    monkeypatch.setattr(anthropic_ai, 'client', fake_anthropic_client(stop_reason))

    response = await anthropic_ai.get_anthropic_response(payload=make_payload('claude-sonnet-5'), context=[], history_tokens=0, prompt_tokens=2)

    assert response.status == status
    assert response.status_code == 200
    assert response.billable is True
    assert response.response == 'Hello'
    assert (response.completion_tokens, response.response_tokens) == (50, 5)

"""
Test if Claude bills only the prompt's own count -> the fake reports input_tokens=12
(system prompt + prompt), the pre-call count of the prompt alone is 2.
"""
async def test_anthropic_does_not_bill_system_prompt(monkeypatch):
    monkeypatch.setattr(anthropic_ai, 'client', fake_anthropic_client('end_turn'))

    response = await anthropic_ai.get_anthropic_response(payload=make_payload('claude-sonnet-5'), context=[], history_tokens=0, prompt_tokens=2)

    assert response.prompt_tokens == 2

"""
Gemini: one chunk with a thought part, an answer part and the finish_reason.
"""
def fake_gemini_client(finish_reason: str):
    chunk = NS(
        usage_metadata=NS(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=45),
        prompt_feedback=None,
        candidates=[NS(finish_reason=NS(name=finish_reason),
                       content=NS(parts=[NS(text='thinking...', thought=True), NS(text='Hello', thought=False)]))],
    )

    async def generate_content_stream(**kwargs):
        return stream_of([chunk])
    return NS(aio=NS(models=NS(generate_content_stream=generate_content_stream)))

@pytest.mark.parametrize('finish_reason, status', [('MAX_TOKENS', 'Truncated'), ('STOP', 'Completed')])
async def test_gemini_status(monkeypatch, finish_reason, status):
    monkeypatch.setattr(google_ai, 'client', fake_gemini_client(finish_reason))

    response = await google_ai.get_gemini_response(payload=make_payload('gemini-3.5-flash'), context=[], history_tokens=0, prompt_tokens=2)

    assert response.status == status
    assert response.status_code == 200
    assert response.billable is True
    assert response.response == 'Hello'
    assert (response.completion_tokens, response.response_tokens) == (50, 5)

"""
Replicate: no finish reason -> an output_token_count that reached max_tokens (50) counts as truncated.
"""
class FakeEvent:
    class EventType:
        OUTPUT = 'output'

    def __init__(self, data: str):
        self.event = 'output'
        self.data = data

class FakePrediction:
    def __init__(self, output_token_count: int):
        self.id = 'fake-prediction'
        self.status = 'succeeded'
        self.error = None
        self.metrics = {'input_token_count': 10, 'output_token_count': output_token_count}

    def async_stream(self):
        return stream_of([FakeEvent('Hello')])

    async def async_reload(self):
        pass

    async def async_cancel(self):
        pass

def fake_replicate_client(output_token_count: int):
    async def async_create(**kwargs):
        return FakePrediction(output_token_count)
    return NS(predictions=NS(async_create=async_create))

@pytest.mark.parametrize('output_token_count, status', [(50, 'Truncated'), (20, 'Completed')])
async def test_replicate_status(monkeypatch, output_token_count, status):
    monkeypatch.setattr(google_ai, 'replicate_client', fake_replicate_client(output_token_count))

    response = await google_ai.get_replicate_response(payload=make_payload('google/gemini-3.1-pro'), context=[], history_tokens=0, prompt_tokens=2)

    assert response.status == status
    assert response.status_code == 200
    assert response.billable is True
    assert response.response == 'Hello'
    assert response.completion_tokens == output_token_count
