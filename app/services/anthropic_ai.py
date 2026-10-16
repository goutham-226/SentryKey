#services/anthropic_ai.py

#Send requests to the Anthropic AI API and handle responses.

#import anthropic to handle exceptions.
import anthropic
#import anthropic async client
from anthropic import AsyncAnthropic

# import app dependencies
from app.services.provider_data import provider_response
from app.config import get_settings
from app.schemas import ChatRequest

import logging

from fastapi import HTTPException, status


#get settings from config.py
settings = get_settings()

logger = logging.getLogger(__name__)

# create async anthropic client.

client = AsyncAnthropic(api_key=settings.anthropic_api_key)

# message returned to the caller when a request fails without producing any tokens.
UNAVAILABLE_MESSAGE = 'Sorry model is not available at the moment please try again later or use a different model'



async def get_anthropic_response(payload: ChatRequest, context: list[dict[str,str]], history_tokens: int, prompt_tokens: int) -> provider_response:
    """
    send a request to Anthropic AI,
    and handle network Errors.
    """
    _request: dict[str,str] = {'role':'user','content':payload.prompt}
    _model: str = payload.model
    _max_tokens: int = payload.max_tokens
    _system_prompt: str = settings.anthropic_system_prompt
    
    context.append(_request) # anthropic uses the same context format as openai, so we can append the user request to the context list.
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
    response_tokens: int = 0

    # declared ahead of the try block so except clauses can read whatever was
    # streamed before the failure.
    parts: list[str] = []
    input_tokens: int | None = None # message_start usage -> system prompt + context + prompt.
    output_tokens: int = 0 # message_delta usage -> cumulative completion tokens.
    thinking_tokens: int = 0 # message_delta usage -> reasoning tokens included in output_tokens.
    stop_reason: str | None = None

    def mid_stream_failure(fallback_status_code: int) -> None:
        """
        Build response fields for an exception that can be raised mid-stream.
        billable only if Anthropic had already generated (and therefore billed
        for) some completion tokens before the failure.
        """
        nonlocal model_response, prompt_tokens, completion_tokens, context_tokens
        nonlocal status_code, status, billable, token_buffer, response_tokens
        if not fallback_status_code >= 400:
            fallback_status_code = 500
        if started_generation:
            model_response = ''.join(parts)
            # no local tokenizer for anthropic and output usage only arrives at the end
            # of the stream -> estimate ~4 chars per token, floored at the last reported usage.
            completion_tokens = max(output_tokens, len(model_response) // 4)
            response_tokens = max(output_tokens - thinking_tokens, len(model_response) // 4)
            token_buffer = 15 # safety buffer for an interrupted/uncounted completion.
            status_code = fallback_status_code
            status = 'Interrupted'
            billable = True
        else:
            model_response = UNAVAILABLE_MESSAGE
            prompt_tokens = 0
            completion_tokens = 0
            context_tokens = 0
            status_code = fallback_status_code
            status = 'Failed'
            billable = False

    def non_billable_failure(fallback_status_code: int) -> None:
        """
        Build response fields for an exception that Anthropic always raises
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

    # send a stream request and raise exceptions
    try:
        async with client.messages.stream(
            model=_model,
            messages=context,
            system=_system_prompt,
            max_tokens=_max_tokens,
        ) as stream:
            async for event in stream:
                if event.type == 'message_start':
                    started_generation = True
                    status = 'Interrupted'
                    input_tokens = event.message.usage.input_tokens
                elif event.type == 'content_block_delta' and event.delta.type == 'text_delta':
                    parts.append(event.delta.text)
                elif event.type == 'message_delta':
                    stop_reason = event.delta.stop_reason
                    output_tokens = event.usage.output_tokens
                    details = event.usage.output_tokens_details
                    thinking_tokens = details.thinking_tokens if details else 0
                # an SSE 'error' event (e.g. overloaded mid-stream) is raised by the SDK
                # as an APIStatusError -> handled by the except clauses below.

        model_response = ''.join(parts)
        if input_tokens is not None:
            # input_tokens includes context (billed to the context quota) and the system prompt.
            # floor at the count_tokens prompt estimate in case context_tokens over-counts.
            prompt_tokens = max(input_tokens - context_tokens, prompt_tokens)
        completion_tokens = output_tokens
        # output_tokens includes thinking tokens -> subtract them for the visible count.
        response_tokens = output_tokens - thinking_tokens
        billable = True
        if stop_reason == 'refusal':
            # refusals are still billed -> anthropic generated (and charged for) the tokens.
            logger.warning("Anthropic refused to generate a response model=%s", _model)
            status_code = 403
            status = 'Refused'
        else:
            status_code = 200
            status = 'Completed'

    # non-billable: Anthropic rejected the request outright - it never started
    # generating a response, so no completion tokens were billed.
    except (
            anthropic.BadRequestError,
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
            anthropic.ConflictError,
            anthropic.UnprocessableEntityError,
            anthropic.RateLimitError,
            anthropic.RequestTooLargeError,
           ) as e:
        logger.warning("Anthropic rejected the request (%s) model=%s", type(e).__name__, _model)
        non_billable_failure(e.status_code)

    # potentially billable: a 5xx (or other) status error that can happen
    # mid-stream, after Anthropic already generated some completion tokens
    # (e.g. 529 overloaded_error sent as an SSE error event).
    except (anthropic.InternalServerError, anthropic.APIStatusError) as e:
        logger.error("Anthropic returned an error (%s) model=%s", type(e).__name__, _model)
        mid_stream_failure(e.status_code)

    # potentially billable: the request timed out, which can happen mid-stream.
    # caught before APIConnectionError -> APITimeoutError subclasses it.
    except anthropic.APITimeoutError:
        logger.error("Anthropic request timed out model=%s", _model)
        mid_stream_failure(504)

    # non-billable: the connection to Anthropic never succeeded.
    except anthropic.APIConnectionError:
        logger.error("Anthropic connection failed model=%s", _model)
        non_billable_failure(503)

    # potentially billable fallback for any other SDK-raised error, e.g. a
    # dropped connection or malformed event mid-stream.
    except anthropic.APIError as e:
        logger.exception("Anthropic stream failed (%s) model=%s", type(e).__name__, _model)
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
                response_tokens=response_tokens,
                token_buffer=token_buffer,
              )


async def get_anthropic_tokens(text: str, model: str,role: str) -> int:
    """
    Get the number of tokens in a text string for a given model.
    """
    # create request json for the anthropic client.
    message: dict[str,str] = {"role":role,"content":text}
    request: list[dict[str,str]] = [message]
    # use the anthropic client to get the number of tokens in the text.
    # model check happens in get_bearer_key dependency, so we can assume the model is valid.
    try:
        result = await client.messages.count_tokens(model=model, messages=request)
    except anthropic.APIError as e:
        logger.exception("count_tokens failed (%s) model=%s",type(e).__name__,model)
        raise HTTPException(
            status_code=500,
            detail="Provider isn't available at the moment.",
        ) 
    # count_tokens returns a MessageTokensCount object, not an int.
    return result.input_tokens
