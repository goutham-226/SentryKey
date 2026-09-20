'''
Provider Module:
---------------
-> Get User and payload and send request to its own company's service (ex: gpt -> openai).

DB schema: 
---------
-> Models Table contains info about context budget and info about input schema.
-> UsageRecords has an update with context_tokens -> every api request with a key now tracks context tokens used.

Conversation Context Logic:
--------------------------
If the user chooses to carry the conversation over, the client sends a json req with a conversation_id and 
every message row mapping to a particular conversation_id is considered as history, only the most recent 1000
tokens are considered per request and this can be done until the daily context quota is met after which this feature
is not supported.


How to handle Exceptions and Manage Being Billed on Network Timeouts:
--------------------------------------------------------------------

OpenAI :
------

Enable Streaming and capture chuncks append them to a string variable.

if the error is one of these:
    RateLimitError
    InternalServerError
    ServiceUnavailableError
    ConflictError

then there is a chance that tokens were processed but could'nt reach our gateway 
for this calculate appended tokens and add a 15 tokens buffer.

and update usage_records with the calculated value send the half generated response -
- or "model did not load properly try again!" if nothing was generated 

lets decide the output structure a data class standard across all models 

{
    reply = output,
    prompt_tokens = prompt_tokens,
    completion_tokens = completion_tokens,
    status_code = status,
    context_used = history, # use tiktoken to count tokens for previous messages.
}

TO_DO FOR 09-21-2026 :
--------------------
- Implement context_window rate limit logic 
- Finish OpenAI response func and make /v1/chat/completions of Sentrykey work with no errors
- Think of rate limiting logic for google or anthropic models

'''
from datetime import datetime
from dataclass import dataclass
from typing import Any

# module classes and func
from app.db import SessionLocal
from app.config import get_settings
from app.models import Users,ApiKeys,UsageRecords,SubscriptionTiers,Models,Conversations,Messages,Subscriptions
from app.schemas import ChatRequest, ChatResponse

# import AI provider clients
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from anthropic import AsyncAnthropic

# import sql-alchemy req
from sqlalchemy import func, select, Date, update, text, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

# fastapi 
from fastapi import HTTPException

#tiktoken a byte pair encoding tokenizer built by OpenAI
import tiktoken

'''
api_key is already checked for access and model privilige
api_key is not checked for quota 
check quota and raise an exceptions
'''

openai_client = AsyncOpenAI()

@dataclass
class provider_response:
    response: str
    prompt_tokens: int
    completion_tokens: int
    status_code: int
    context_used: int

async def get_openai_response(payload: ChatRequest, conversation_history: list[Messages], available_context_tokens: int) -> provider_response:
    encode = tiktoken.get_encoding("o200k_base") # openai uses o200k_base for all its gpt-5+ models
    prompt_tokens = len(encoding.encode(payload.prompt))
    # now iterate through Messages and contruct history
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
    if payload.conversation_id is not None:
        context_tokens = 0 
        '''
        #   Context_tokens keeps a track of the sum of the content tokens + role tokens, 
            if it ever exceeds our limit the loop just breaks.

        #   But if we want to capture all the tokens before the limit is hit this will cause problems,
            consider a scenario where all computed prev_message_tokens is 500 and one new message with 600 tokens,
            our logic of just keeping a sum would ignore all 600 tokens of the new message because 500 + 600 > limit
            we need to avoid this and consider 500 tokens of the new message and ignore the extra 100.

        #   How do we avoid this:
            --------------------
            First we need to calculate the number of tokens our 'content' str is exceeding because role is constant
            we do this by : 
                number_tokens_we_need_to_keep = content_tokens - (context_tokens - context_token_limit_per_req)
                if this number is 0:
                   break
                tokens = encoding.encode(content) #returns token_id list
                tokens = tokens[:number_tokens_we_need_to_keep] #only the first n tokens that dont exceed our limit
                content = encoding.decode(tokens) # -> decode token_ids back to string
                my_dict = {"role":role,"content":content}
                history.append(my_dict)
                break
            
        '''
        for conversation in conversation_history: # list is Newest to oldest so capture the latest conversation below the 1000 token limit for each request
            role = conversation.role
            role_tokens = len(encoding.encode(role))
            content = conversation.content
            content_tokens = len(encoding.encode(content))
            context_tokens += (content_tokens + role_tokens) 
            if role_tokens + content_tokens > context_token_limit_per_req:
                break
            my_dict = {"role":role,"content":content}
            history.append(my_dict)
    new_req = {"role":"user","content":payload.prompt}
    history.append(new_req)
    # now that we have our history built lets call the provider
    streamed_output = ''
    try:
        stream = await openai_client.chat.completions.create(
            model=payload.model,
            messages=history,

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
        ) # func.coalesce returns 0 if todays usage records are None
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
        stmt = select(Models.provider).where(Model.model_id == model_name)
        result = await db.execute(stmt)
        provider = result.scalar_one_or_none()
        # if conversation_id is sent get previous messages
        if payload.conversation_id is not None:
            stmt = select(Messages).where(Messages.conversation_id == payload.conversation_id).order_by(desc(Messages.created_on))
            result = await db.execute(stmt)
            conversation_history = result.scalars().all() # an iterable list of ORM objects.
        # check if there are available context tokens and return how many
        stmt = select(func.coalesce(func.sum(UsageRecords.context_tokens))).where(
            UsageRecords.requested_at + text("INTERVAL '1 day") > func.now(),
        )
        # sum of context_tokens on todays usage record row
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
            chat_response = get_openai_response(payload,conversation_history,available_context_tokens)
            
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
    




        

        










































        

        
        
         
