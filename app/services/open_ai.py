#services/open_ai.py
"""
Send requests to OpenAI SDK,
Handle exceptions and Network timeouts.
"""
#import openai to handle exceptions
import openai
# import openai async client
from openai import AsyncOpenAI
#open-ai encoder returns a list of token_ids
import tiktoken
# import asyncio to offload encoding onto a thread.
import asyncio
# import app dependencies
from app.config import Settings,get_settings
from app.schemas import ChatRequest
# import service dependencies
from app.services.provider_data import provider_response

settings: Settings = get_settings()

client = AsyncOpenAI(api_key=settings.openai_api_key)

encoding = tiktoken.get_encoding('o200k_base')

# message returned to the caller when a request fails without producing any tokens.
UNAVAILABLE_MESSAGE = 'Sorry model is not available at the moment please try again later or use a different model'


async def get_openai_response(payload: ChatRequest, context: list[dict[str,str]]) -> provider_response:
    """
    send a request to OpenAI,
    and handle network Errors.
    """
    _request: dict[str,str] = {'role':'user','content':payload.prompt}
    _model: str = payload.model
    _max_tokens: int = payload.max_tokens
    context.reverse() # we reversed the order while trimming context. -> older - newer
    context.append(_request)
    # initialise variables to set dataclass attributes.
    model_response: str = ''
    prompt_tokens: int = await get_openai_tokens(payload.prompt)
    completion_tokens: int = 0
    context_tokens: int = 0
    status_code: int = 0
    status: str = 'Incomplete'
    started_generation: bool = False
    billable: bool = False
    # declared ahead of the try block so except clauses can read whatever was
    # streamed before the failure.
    token_counter: int = 0
    parts: list[str] = []
    usage = None

    def mid_stream_failure(fallback_status_code: int) -> None:
        """
        Build response fields for an exception that can be raised mid-stream.
        billable only if OpenAI had already generated (and therefore billed
        for) some completion tokens before the failure.
        """
        nonlocal model_response, prompt_tokens, completion_tokens, context_tokens
        nonlocal status_code, status, billable
        if started_generation:
            model_response = ''.join(parts)
            completion_tokens = token_counter + 15 # safety buffer for an interrupted/uncounted completion.
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
        Build response fields for an exception that OpenAI always raises
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
        stream = await client.chat.completions.create(
                             model= _model,
                             messages=context,
                             stream=True,
                             stream_options={'include_usage':True},
                             max_completion_tokens= _max_tokens,
                           )

        async for chunk in stream:
            started_generation = True
            status = 'Interrupted'
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices: # empty list did not capture tokens yet
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                token_counter += len(encoding.encode(delta))
                parts.append(delta)

        model_response = ''.join(parts)
        if usage is not None:
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
        else:
            completion_tokens = token_counter
        completion_tokens += 15 # token_buffer added for all billable generations.
        status_code = 200
        status = 'Completed'
        billable = True

    # non-billable: OpenAI rejected the request outright - it never started
    # generating a response, so no completion tokens were billed.
    except (
            openai.BadRequestError,
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
            openai.ConflictError,
            openai.UnprocessableEntityError,
            openai.RateLimitError,
           ) as e:
        non_billable_failure(e.status_code)

    # potentially billable: a 5xx (or other) status error that can happen
    # mid-stream, after OpenAI already generated some completion tokens.
    except (openai.InternalServerError, openai.APIStatusError) as e:
        mid_stream_failure(e.status_code)

    # potentially billable: the request timed out, which can happen mid-stream.
    except openai.APITimeoutError:
        mid_stream_failure(504)

    # non-billable: the connection to OpenAI never succeeded.
    except openai.APIConnectionError:
        non_billable_failure(503)

    # potentially billable fallback for any other SDK-raised error, e.g. a
    # dropped connection or malformed chunk mid-stream.
    except openai.APIError:
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
              )


async def get_openai_tokens(text: str) -> int:
    """
    Return OpenAI token estimate
    using tiktoken.
    """
    token_ids = await asyncio.to_thread(encoding.encode, text)
    token_len = len(token_ids)
    return token_len
