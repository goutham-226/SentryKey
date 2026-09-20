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

'''
from datetime import datetime

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
from sqlalchemy import func, select, Date, update, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

# fastapi 
from fastapi import HTTPException

'''
api_key is already checked for access and model privilige
api_key is not checked for quota
check quota and raise an exceptions
'''



async def get_response(api_key: ApiKeys,payload: ChatRequest) -> ChatResponse:
    #get payload variables
    input_prompt = payload.prompt
    model_name = payload.model
    max_tokens = payload.max_tokens
    conversation_id = payload.conversation_id
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
        #end of db reads
    #exit connection pool for chat request(long transaction prone to Network timeouts)
    # manage max_tokens so it never exceeds input_tokens + token_count
    tokens_available = (api_key.daily_quota) - (input_tokens + token_count)
    max_tokens = min(max_tokens,tokens_available)
    # now check payload model provider and send requests
    if provider == 'openai':
            chat_response = get_openai_response(payload)
            # extract results
            reply = chat_response.choices[0].message.content
            input_tokens = chat_response.usage.prompt_tokens
            completion_tokens = chat_response.usage.completion_tokens
            # open a session and write to DB
    if provider == 'anthropic':
        chat_response = get_anthropic_response(payload)
    if provider == 'google':
        chat_response = get_google_response(payload)
    




        

        










































        

        
        
         
