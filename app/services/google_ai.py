#google_ai.py

# send a request to Gemini and handle responses.
from google import genai
from google.genai import errors, models, types
#import httpx to handle network exceptions -> the genai and replicate SDKs do not wrap timeouts / connection errors.
import httpx
import replicate
from replicate.exceptions import ReplicateError
from replicate.prediction import Prediction

from app.config import get_settings
from app.schemas import ChatRequest
from app.services.provider_data import provider_response

import asyncio
import logging


settings = get_settings()

logger = logging.getLogger(__name__)

# timeout is in milliseconds and applies per read -> a stream that stalls for 60s raises httpx.ReadTimeout.
# without it the SDK never times out. retries stay off (SDK default) -> failures settle through the reservation.
client = genai.Client(api_key=settings.google_api_key, http_options=types.HttpOptions(timeout=60_000))
# replicate 1.x has no AsyncReplicate -> replicate.Client exposes async_* methods.
# read timeout applies per read, same as the genai client.
replicate_client = replicate.Client(api_token=settings.replicate_api_token, timeout=httpx.Timeout(60.0, connect=10.0))

# gemini served through replicate -> billed by replicate, not google.
REPLICATE_GEMINI_MODEL = 'google/gemini-3.1-pro'

# message returned to the caller when a request fails without producing any tokens.
UNAVAILABLE_MESSAGE = 'Sorry model is not available at the moment please try again later or use a different model'

# finish / block reasons where Gemini refused to answer -> still billed like anthropic refusals.
REFUSAL_REASONS = {'SAFETY', 'RECITATION', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII', 'MODEL_ARMOR', 'JAILBREAK', 'OTHER'}


async def get_gemini_response(payload: ChatRequest, context: list[dict[str,str]], history_tokens: int, prompt_tokens: int) -> provider_response:
    """
    send a request to Gemini,
    and handle network Errors.
    """
    contents = handle_context(context=context, prompt=payload.prompt)
    _model: str = payload.model
    _max_tokens: int = payload.max_tokens

    # initialise variables to set dataclass attributes.
    model_response: str = ''
    # prompt_tokens is passed in -> already counted by get_response, no second count_tokens call.
    completion_tokens: int = 0
    context_tokens: int = history_tokens
    status_code: int = 0
    status: str = 'Incomplete'
    started_generation: bool = False
    billable: bool = False
    token_buffer: int = 0

    # declared ahead of the try block so except clauses can read whatever was
    # streamed before the failure.
    parts: list[str] = []
    usage: types.GenerateContentResponseUsageMetadata | None = None # last usage_metadata seen -> cumulative.
    finish_reason: str | None = None
    block_reason: str | None = None

    def output_tokens() -> int:
        """
        Completion tokens from the last reported usage -> thinking tokens are billed as output.
        """
        if usage is None:
            return 0
        return (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)

    def non_billable_failure(fallback_status_code: int) -> None:
        """
        Build response fields for an exception that Gemini always raises
        before generating a single token - nothing was billed.
        """
        nonlocal model_response, prompt_tokens, completion_tokens, context_tokens
        nonlocal status_code, status, billable
        model_response = UNAVAILABLE_MESSAGE
        prompt_tokens = 0
        completion_tokens = 0
        context_tokens = 0
        status_code = fallback_status_code
        status = 'Failed'
        billable = False

    def mid_stream_failure(fallback_status_code: int) -> None:
        """
        Build response fields for an exception that can be raised mid-stream.
        billable only if Gemini had already generated (and therefore billed
        for) some completion tokens before the failure.
        """
        nonlocal model_response, completion_tokens, status_code, status, billable, token_buffer
        if started_generation:
            model_response = ''.join(parts)
            # usage may lag behind the text already streamed (or never arrive)
            # -> estimate ~4 chars per token, floored at the last reported usage.
            completion_tokens = max(output_tokens(), len(model_response) // 4)
            token_buffer = 15 # safety buffer for an interrupted/uncounted completion.
            status_code = fallback_status_code
            status = 'Interrupted'
            billable = True
        else:
            non_billable_failure(fallback_status_code)

    # send a stream request and raise exceptions
    try:
        async for chunk in await client.aio.models.generate_content_stream(
            model=_model,
            contents=contents,
            config=types.GenerateContentConfig(max_output_tokens=_max_tokens),
        ):
            # first chunk received -> Gemini accepted the request and started generating.
            started_generation = True
            status = 'Interrupted'
            if chunk.usage_metadata:
                usage = chunk.usage_metadata
            if chunk.prompt_feedback and chunk.prompt_feedback.block_reason:
                block_reason = chunk.prompt_feedback.block_reason.name
            if chunk.candidates:
                candidate = chunk.candidates[0]
                if candidate.finish_reason:
                    finish_reason = candidate.finish_reason.name
                if candidate.content and candidate.content.parts:
                    # skip thought parts -> only the answer is returned to the caller.
                    parts.extend(part.text for part in candidate.content.parts if part.text and not part.thought)

        model_response = ''.join(parts)
        if usage is not None and usage.prompt_token_count is not None:
            # prompt_token_count includes context (billed to the context quota).
            # floor at the count_tokens prompt estimate in case context_tokens over-counts.
            prompt_tokens = max(usage.prompt_token_count - context_tokens, prompt_tokens)
        completion_tokens = output_tokens()
        billable = True
        if block_reason in REFUSAL_REASONS or finish_reason in REFUSAL_REASONS:
            # refusals are still billed -> the prompt was processed (and charged for).
            logger.warning("Gemini refused to generate a response (%s) model=%s", block_reason or finish_reason, _model)
            status_code = 403
            status = 'Refused'
        else:
            status_code = 200
            status = 'Completed'

    # non-billable: Gemini rejected the request outright with a 4xx
    # (400 invalid, 403 key, 404 model, 429 quota) before generating anything.
    except errors.ClientError as e:
        logger.warning("Gemini rejected the request (%s %s) model=%s", e.code, e.status, _model)
        non_billable_failure(e.code)

    # potentially billable: a 5xx (or other) API error that can happen mid-stream.
    except errors.APIError as e:
        logger.error("Gemini returned an error (%s %s) model=%s", e.code, e.status, _model)
        mid_stream_failure(e.code or 500)

    # potentially billable: a read stalled past the timeout, which can happen mid-stream.
    # caught before TransportError -> TimeoutException subclasses it.
    except httpx.TimeoutException:
        logger.error("Gemini request timed out model=%s", _model)
        mid_stream_failure(504)

    # connect failure (non-billable -> started_generation is still False) or a
    # dropped connection mid-stream (billable for what was already generated).
    except httpx.TransportError as e:
        logger.error("Gemini connection failed (%s) model=%s", type(e).__name__, _model)
        mid_stream_failure(503)

    # potentially billable fallback for a malformed response mid-stream.
    except errors.UnknownApiResponseError:
        logger.exception("Gemini stream failed model=%s", _model)
        mid_stream_failure(500)

    return provider_response(
                response=model_response,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                context_tokens=context_tokens,
                status_code=status_code,
                status=status,
                started_generation=started_generation,
                billable=billable,
                token_buffer=token_buffer,
              )


async def get_replicate_response(payload: ChatRequest, context: list[dict[str,str]], history_tokens: int, prompt_tokens: int) -> provider_response:
    """
    send a request to gemini-3.1-pro on Replicate,
    and handle network Errors.
    """
    _prompt: str = handle_replicate_context(context=context, prompt=payload.prompt)
    _max_tokens: int = payload.max_tokens

    # initialise variables to set dataclass attributes.
    model_response: str = ''
    # prompt_tokens is passed in -> already counted by get_response.
    completion_tokens: int = 0
    context_tokens: int = history_tokens
    status_code: int = 0
    status: str = 'Incomplete'
    started_generation: bool = False
    billable: bool = False
    token_buffer: int = 0

    # declared ahead of the try block so except clauses can read whatever was
    # streamed before the failure.
    parts: list[str] = []
    prediction: Prediction | None = None

    def non_billable_failure(fallback_status_code: int) -> None:
        """
        Build response fields for an exception raised before
        Replicate generated a single token - nothing was billed.
        """
        nonlocal model_response, prompt_tokens, completion_tokens, context_tokens
        nonlocal status_code, status, billable
        model_response = UNAVAILABLE_MESSAGE
        prompt_tokens = 0
        completion_tokens = 0
        context_tokens = 0
        status_code = fallback_status_code
        status = 'Failed'
        billable = False

    def mid_stream_failure(fallback_status_code: int) -> None:
        """
        Build response fields for an exception that can be raised mid-stream.
        billable only if Replicate had already streamed (and therefore billed
        for) some completion tokens before the failure.
        """
        nonlocal model_response, completion_tokens, status_code, status, billable, token_buffer
        if started_generation:
            model_response = ''.join(parts)
            # no usage until the prediction finishes -> estimate ~4 chars per token.
            completion_tokens = len(model_response) // 4
            token_buffer = 15 # safety buffer for an interrupted/uncounted completion.
            status_code = fallback_status_code
            status = 'Interrupted'
            billable = True
        else:
            non_billable_failure(fallback_status_code)

    async def cancel_prediction() -> None:
        """
        Cancel the prediction on Replicate -> it keeps generating (and billing)
        after our connection drops unless it is cancelled.
        """
        if prediction is None:
            return
        try:
            await prediction.async_cancel()
        except Exception:
            logger.exception("Failed to cancel Replicate prediction %s", prediction.id)

    # send a stream request and raise exceptions
    try:
        prediction = await replicate_client.predictions.async_create(
            model=REPLICATE_GEMINI_MODEL,
            input={'prompt': _prompt, 'max_output_tokens': _max_tokens},
            stream=True,
        )
        async for event in prediction.async_stream():
            # an SSE 'error' event is raised by the SDK as a RuntimeError -> handled below.
            if event.event == event.EventType.OUTPUT:
                # first output event -> Replicate is generating and billing.
                started_generation = True
                status = 'Interrupted'
                parts.append(event.data)

        # stream finished -> reload for the final status and token metrics.
        await prediction.async_reload()
        model_response = ''.join(parts)
        if prediction.status != 'succeeded':
            logger.error("Replicate prediction %s ended as %s: %s", prediction.id, prediction.status, prediction.error)
            mid_stream_failure(500)
        else:
            metrics = prediction.metrics or {}
            input_token_count = metrics.get('input_token_count')
            output_token_count = metrics.get('output_token_count')
            if input_token_count is not None:
                # input_token_count includes the history string (billed to the context quota).
                # floor at the prompt estimate in case context_tokens over-counts.
                prompt_tokens = max(input_token_count - context_tokens, prompt_tokens)
            if output_token_count is not None:
                completion_tokens = output_token_count
            else:
                # metrics missing -> estimate ~4 chars per token with the safety buffer.
                completion_tokens = len(model_response) // 4
                token_buffer = 15
            billable = True
            status_code = 200
            status = 'Completed'

    # Replicate rejected the request (401 token, 402 billing, 404 model, 422 input, 429 rate limit)
    # -> non-billable when the prediction was never created or never streamed.
    except ReplicateError as e:
        logger.warning("Replicate rejected the request (%s %s) model=%s", e.status, e.title, REPLICATE_GEMINI_MODEL)
        await cancel_prediction()
        mid_stream_failure(e.status or 500)

    # potentially billable: a read stalled past the timeout, which can happen mid-stream.
    # caught before TransportError -> TimeoutException subclasses it.
    except httpx.TimeoutException:
        logger.error("Replicate request timed out model=%s", REPLICATE_GEMINI_MODEL)
        await cancel_prediction()
        mid_stream_failure(504)

    # connect failure (non-billable -> started_generation is still False) or a
    # dropped connection mid-stream (billable for what was already generated).
    except httpx.TransportError as e:
        logger.error("Replicate connection failed (%s) model=%s", type(e).__name__, REPLICATE_GEMINI_MODEL)
        await cancel_prediction()
        mid_stream_failure(503)

    # potentially billable: the model sent an SSE error event mid-stream.
    except RuntimeError as e:
        logger.error("Replicate stream failed (%s) model=%s", e, REPLICATE_GEMINI_MODEL)
        await cancel_prediction()
        mid_stream_failure(500)

    # request cancelled while awaiting Replicate -> stop the prediction, then let
    # provider_service release the reservation.
    except asyncio.CancelledError:
        await cancel_prediction()
        raise

    return provider_response(
                response=model_response,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                context_tokens=context_tokens,
                status_code=status_code,
                status=status,
                started_generation=started_generation,
                billable=billable,
                token_buffer=token_buffer,
              )


def handle_replicate_context(context: list[dict[str,str]], prompt: str) -> str:
    """
    Concatenate the context into a single string -> Replicate takes one prompt string,
    not a list of turns.
    """
    history = '\n'.join(f"{message['role']}: {message['content']}" for message in context if message.get('role') and message.get('content'))
    return f"history: {history}, current = {prompt}"


def handle_context(context: list[dict[str,str]],prompt: str) -> list[dict]:
    """
    Convert the context list of dictionaries into Gemini's contents format,
    with the user prompt as the last turn.
    """
    history = []
    parts_list = []
    parts_dict = {}
    for message in context:
        role = message.get('role')
        content = message.get('content')
        if role and content:
            parts_list = []
            parts_dict = {'text':content}
            parts_list.append(parts_dict)
            if role == 'assistant':
                role = 'model'
            history.append({'role': role, 'parts': parts_list})
    parts_dict = {'text':prompt}
    history.append({'role': 'user', 'parts': [parts_dict]})
    
    return history
            



async def get_gemini_tokens(text: str, model: str) -> int:
    """
    Get the number of tokens in a given text using the Gemini API.
    """
    if model == 'google/gemini-3.1-pro':
        model = 'gemini-3.1-pro'  
    response = await client.aio.models.count_tokens(
        model=model,
        contents=text,
    )
    return response.total_tokens
    
    