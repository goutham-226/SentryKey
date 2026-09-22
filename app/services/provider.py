"""
Provider Module:
===============
-> Get User and payload and send request to its own company's service (ex: gpt -> OpenAI).

DB schema:
=========
-> Models Table contains info about context budget and info about input schema.
-> UsageRecords has an update with context_tokens -> every api request with a key now tracks context tokens used.

Conversation Context Logic:
==========================
If the user chooses to carry the conversation over, the client sends a JSON req with a conversation_id and
every message row mapping to a particular conversation_id is considered as history, only the most recent 1000
tokens are considered per request and this can be done until the daily context quota is met after which this feature
is not supported.


How to handle Exceptions and Manage Being Billed on Network Timeouts:
====================================================================

OpenAI :
------
Sometimes OpenAI SDK can raise Errors and some of these Errors are billable i.e. the tokens
have been processed in such cases we need to handle token counting and ledgering
so we don't lose money on Network errors.

let's decide the output structure ,a data class ,standard across all models

{
    reply = output,
    prompt_tokens = prompt_tokens,
    completion_tokens = completion_tokens,
    status_code = status,
    context_used = history, # use tiktoken to count tokens for previous messages.
}

Enable streaming to capture tokens real time, if we capture all tokens and completion is successful with no Network Errors
then we record the call in the final block and return our dataclass, if the SDK ever raises an error we can classify known errors
into billable and non-billable and handle tokens processed:

-> non_billable - prompt and completion tokens = 0

-> billable - keep count of tokens from the stream add a 15-token buffer and send prompt + completion tokens

Exceptions -

Never billable — the request was rejected before inference:
----------------------------------------------------------
BadRequestError, AuthenticationError, OAuthError, PermissionDeniedError, NotFoundError, ConflictError, UnprocessableEntityError
RateLimitError — you were turned away, nothing ran
InternalServerError and APIConnectionError / APITimeoutError, but only if raised before the first chunk arrived
InvalidWebhookSignatureError — unrelated to inference

Always billable — generation completed or nearly so:
--------------------------------------------------
LengthFinishReasonError — the model produced a full max_tokens worth of output. This is the most expensive error in the list.
ContentFilterFinishReasonError — generation ran, then got cut. Usually billed.
A clean finish. Obviously, but worth stating: that's the case where usage is real.

Unknown — generation started, then broke:
-----------------------------------------
APIConnectionError / APITimeoutError raised during the async for
InternalServerError raised mid-stream
asyncio.CancelledError from a client disconnect (once you're actually streaming out)
Raw httpx exceptions that escape the SDK's wrapping mid-stream





Context-Window-Budget Handling: [message/conversation History] [OpenAI]
==============================
#   Context_tokens keeps a track of the sum of the content tokens + role tokens,
    if it ever exceeds our limit the loop just breaks.

#   But if we want to capture all the tokens before the limit is hit this will cause problems,
    consider a scenario where all computed prev_message_tokens is 500 and one new message with 600 tokens,
    our logic of just keeping a sum would ignore all 600 tokens of the new message because 500 + 600 > limit
    we need to avoid this and consider 500 tokens of the new message and ignore the extra 100 tokens.

#   How do we avoid this:
    --------------------
    We need to calculate the number of tokens our 'content' str is exceeding by because role is constant
    we do this by :
        number_tokens_we_need_to_keep = content_tokens - (context_tokens - context_token_limit_per_req)
        if this number is 0:
            break
        tokens = encoding.encode(content) #returns token_id list
        tokens = tokens[:number_tokens_we_need_to_keep] #only the first n tokens that don't exceed our limit
        content = encoding.decode(tokens) # -> decode token_ids back to string
        my_dict = {"role":role,"content":content}
        history.append(my_dict)
        break


TO_DO:
-----
- Implement context_window rate limit logic - completed

- Finish OpenAI response func and make /v1/chat/completions of Sentrykey work with no errors
- Think of rate limiting logic for Google or anthropic models

"""
from dataclasses import dataclass

# tiktoken a byte pair encoding tokenizer built by OpenAI
import tiktoken
# fastapi
from fastapi import HTTPException
# import AI provider clients
import openai
from openai import AsyncOpenAI
# import sql-alchemy req
from sqlalchemy import func, select, text, desc

# module classes and func
from app.db import SessionLocal
from app.models import ApiKeys, UsageRecords, Models, Messages, Conversations
from app.schemas import ChatRequest, ChatResponse
from app.config import get_settings

'''
api_key is already checked for access and model privilege
api_key is not checked for quota 
check quota and raise an exceptions
'''

settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

@dataclass
class provider_response:
    response: str
    prompt_tokens: int
    completion_tokens: int
    status_code: int
    context_used: int
    status: str

async def get_openai_response(payload: ChatRequest, conversation_history: list[Messages], available_context_tokens: int, max_tokens: int) -> provider_response:
    encoding = tiktoken.get_encoding("o200k_base") # openai uses o200k_base for all its gpt-5+ models
    prompt_tokens = len(encoding.encode(payload.prompt))
    # now iterate through Messages and construct history
    # Chat Completions multimodal user message
    '''
    OpenAI message history schema:
    messages = [{"role": "user|assistant", "content": "content....."}]

    last message is the current input prompt
    so history is list[dict[str,str]]
    '''
    history = []
    context_token_limit_per_req = min(available_context_tokens,1000)
    # iterate through conversation_history and construct history if conversation_id is not None
    context_tokens = 0
    if payload.conversation_id is not None:

        for conversation in conversation_history: # list is Newest to oldest so capture the latest conversation below the 1000 token limit for each request
            role = conversation.role
            role_tokens = len(encoding.encode(role))
            content = conversation.content
            content_tokens = len(encoding.encode(content))
            context_tokens += (content_tokens + role_tokens) 
            if context_tokens > context_token_limit_per_req:
                # number of tokens we need to keep from our last message.
                keep = content_tokens - (context_tokens - context_token_limit_per_req)
                if keep == 0:
                    context_tokens -= (content_tokens + role_tokens)# there are 0 tokens we can append because the limit is already reached
                    break
                token_id_list = encoding.encode(content) # convert message content string into a list of tokens
                token_id_list = token_id_list[:keep] # get the first tokens within our limit
                content = encoding.decode(token_id_list) # decode converts token list into a string literal
                context_tokens = context_tokens - content_tokens
                content_tokens = len(encoding.encode(content))
                context_tokens += content_tokens
                my_dict = {"role":role,"content":content}
                history.append(my_dict)
                break
            my_dict = {"role":role,"content":content}
            history.append(my_dict)
    history.reverse() # since list is newest to oldest the first append is new and last is the oldest to avoid bad perf of the model make sure list is oldest to newest
    new_req = {"role":"user","content":payload.prompt}
    history.append(new_req)
    # now that we have our history built lets call the provider
    model_response = ''
    prompt_tokens = len(encoding.encode(payload.prompt))
    completion_tokens = 0
    status_code = 0
    context_used = 0
    started_generation = False
    status = 'incomplete'
    try:
        stream = await openai_client.chat.completions.create(
            model=payload.model,
            messages=history,
            stream=True,
            stream_options={"include_usage": True},
            max_completion_tokens=max_tokens,
        )
        token_counter = 0
        usage = None
        parts = []
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
        if usage is not None:
            model_response = ''.join(parts)
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            status_code = 200
            context_used = context_tokens
        else:
            model_response = ''.join(parts)
            completion_tokens = token_counter
            status_code = 200
            context_used = context_tokens
        status = 'completed'
    except openai.APIError as e:
        if started_generation:
            model_response = ''.join(parts)
            completion_tokens = token_counter + 15
            status_code = 500 # default to internal server Error actual logs would be on openai dashboard
            context_used = context_tokens
        else:
            model_response= 'Sorry model is not available at the moment please try again later or use a different model'
            completion_tokens = 0
            status_code = 500
            context_used = 0
            prompt_tokens = 0

    return provider_response(
        response=model_response,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        status_code=status_code,
        context_used=context_used,
        status=status,
    )



async def get_response(api_key: ApiKeys,payload: ChatRequest) -> ChatResponse:
    #get payload variables
    input_prompt = payload.prompt
    model_name = payload.model
    max_tokens = payload.max_tokens
    conversation_history = []

    # open a db session pool and check if quota is exceeded
    async with SessionLocal() as db:
        # get today's token usage, use ledger sum
        stmt = select(func.coalesce(func.sum(UsageRecords.prompt_tokens + UsageRecords.completion_tokens))).where(
            UsageRecords.api_key_id == api_key.id,
            UsageRecords.requested_at + text("INTERVAL '1 day'") > func.now(),
        ) # func.coalesce returns 0 if today's usage records are None
        result = await db.execute(stmt)
        token_count = result.scalar()
        # if token_count is greater than daily_quota raise 429
        if token_count > api_key.daily_quota :
            raise HTTPException(
                status_code=429,
                detail='limit exceeded, too many requests',
            )
        # if token_count combined with input_tokens is > daily_quota raise 429
        input_tokens = len(input_prompt.split())
        if (token_count + input_tokens) > api_key.daily_quota:
            raise HTTPException(
                status_code=429,
                detail='limit exceeded, too many requests',
            )
        stmt = select(Models).where(Models.model_id == model_name)
        result = await db.execute(stmt)
        model = result.scalar_one_or_none()
        provider = model.provider

        # if conversation_id is sent get previous messages
        if payload.conversation_id is not None:
            stmt = select(Conversations).where(
                Conversations.id == payload.conversation_id,
                Conversations.api_key_id == api_key.id,
            )
            result = await db.execute(stmt)
            conversation = result.scalar_one_or_none()
            stmt = select(Messages).where(Messages.conversation_id == conversation.id ).order_by(desc(Messages.created_on))
            result = await db.execute(stmt)
            conversation_history = result.scalars().all() # an iterable list of ORM objects.
        # check if there are available context tokens and return how many
        stmt = select(func.coalesce(func.sum(UsageRecords.context_tokens))).where(
            UsageRecords.api_key_id == api_key.id,
            UsageRecords.requested_at + text("INTERVAL '1 day'") > func.now(),
        )
        # sum of context_tokens on today's usage record row
        result = await db.execute(stmt)
        context_sum = result.scalar()
        available_context_tokens = api_key.daily_context_quota - context_sum

        #end of db reads
    #exit connection pool for chat request(long transaction prone to Network timeouts)
    # manage max_tokens so it never exceeds input_tokens + token_count
    tokens_available = (api_key.daily_quota) - (input_tokens + token_count)
    max_tokens = min(max_tokens,tokens_available)
    # now check payload model provider and send requests
    if provider == 'openai':
            chat_response = await get_openai_response(payload,conversation_history,available_context_tokens,max_tokens)
            model_name = payload.model
            output = chat_response.response
            prompt_tokens = chat_response.prompt_tokens
            completion_tokens = chat_response.completion_tokens
            context_quota_used = chat_response.context_used
            status_code = chat_response.status_code
            status = chat_response.status
            tokens_used = token_count + prompt_tokens + completion_tokens
    elif provider == 'anthropic':
        raise HTTPException(
            status_code=400,
            detail='provider not available at the moment'
        )
    elif provider == 'google':
        raise HTTPException(
            status_code=400,
            detail='provider not available at the moment'
        )
    else:
        raise HTTPException(
            status_code=400,
            detail='provider not available at the moment'
        )
    # write to db and return
    async with SessionLocal() as db:
        #check if conversation_id exists
        stmt = select(Conversations).where(
            Conversations.id == payload.conversation_id,
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation is None:
            conversation = Conversations(
                api_key_id = api_key.id,
                title = payload.prompt[:15],
            )
            db.add(conversation)
            await db.flush()
        user_message = Messages(
            conversation_id = conversation.id,
            role = 'user',
            content = payload.prompt,
            token_count=prompt_tokens,
        )
        db.add(user_message)
        await db.flush()
        assistance_message = Messages(
            conversation_id = conversation.id,
            role = 'assistant',
            content = output,
            token_count=completion_tokens,
        )
        db.add(assistance_message)
        await db.flush()
        #update usage records
        usage = UsageRecords(
            api_key_id = api_key.id,
            model_id=model.id,
            conversation_id = conversation.id,
            prompt_tokens = prompt_tokens,
            completion_tokens = completion_tokens,
            context_tokens=context_quota_used,
            status_code=status_code,
            status = status,
        )
        db.add(usage)
        await db.commit()

    #return chat response
    return ChatResponse(
        model=model_name,
        output=output,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        quota_remaining=(api_key.daily_quota - tokens_used),
        conversation_id=conversation.id,
        error_detail=status,
    )

        

        










































        

        
        
         
