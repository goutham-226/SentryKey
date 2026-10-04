#services/provider_response.py
'''
A module with a method to get a chat request,
from POST /v1/chat/completions and return a
processed response.

get_response():
--------------
-> gets in a chat_request_payload,
   and an api_key.
-> checks quota requirement.
-> checks context limits.
-> creates context.
-> passes a request to a specific provider_function ex: open_ai_response, anthropic_resposne .. etc.
-> gets a standard dataclass across all providers.


'''
#import fastapi HTTPException
from fastapi import HTTPException
# import sqlalchemy
from sqlalchemy import select, text, func
#import db session
from app.db import SessionLocal
# import ChatRequest schema
from app.schemas import ChatRequest
#import ApiKey model
from app.models import ApiKeys, UsageRecords, Models
#import dataclass
from app.services.provider_data import provider_response
from app.services.open_ai import get_openai_prompt_tokens


async def get_total_tokens(api_key: ApiKeys, db: AsyncSession) -> int:
    """
    A method to calculate
    total tokens used today.
    """
    stmt = select(func.coalesce(func.sum(UsageRecords.prompt_tokens + UsageRecords.completion_tokens),0)).where(
                               UsageRecords.api_key_id == api_key.id,
                               UsageRecords.requested_at + text("INTERVAL '1 day'") > func.now(),
                             )
    result = await db.execute(stmt)
    total_tokens = result.scalar() # a single integer value of the total sum.
    
    return total_tokens
 
async def get_model_provider(model: str,db: AsyncSession) -> str:
    """
    A method to get a model's provider.
    """
    stmt = select(Models.provider).where(Models.model_id == model)
    result = await db.execute(stmt)
    provider = result.scalar_one_or_none()

    return provider 
    

async def get_response(payload: ChatRequest, api_key: ApiKeys, db: AsyncSession) -> provider_response:
    """
    get_response method takes 
    in payload and api_key,
    and routes it to a provider - current service inly provides 9 models from 3 providers
    openai,
    anthropic,
    gemini.
    returns a response.

    Handles rate-limiting, and context building.
    """

    _prompt = payload.prompt
    _model = payload.model
    _max_tokens = payload.max_tokens
    _conversation_id = payload.conversation_id 
    # get daily token limit
    daily_token_limit = api_key.daily_quota

    # get provider for the payload model.
    _provider = await get_model_provider(model=_model,db=db)
    # get_input_tokens from a model provider.
    if _provider == 'openai':
        # uses tiktoken synchronous function. 
        prompt_tokens = get_openai_prompt_tokens(prompt=_prompt)

    elif _provider == 'anthropic':
        # model not available at this moment
        raise HTTPException(
                      status_code = 404,
                      detail = 'Model not available at the moment.',
                     ) 

    elif _provider == 'google':
        # model not available at the moment
        raise HTTPException(
                       status_code = 404,
                       detail = 'Model not available at the moment.',
                     )

    else:
        raise HTTPException(
                     status_code = 404,
                     detail = 'Model not provided by our service.',
                    )

    
    total_tokens_used = await get_total_tokens(api_key=api_key,db=db) 
    # total_tokens = used_tokens + prompt_tokens
    total_tokens = total_tokens_used + prompt_tokens
    # if used tokens + prompt_tokens exceed quota limit raise HTTException.
    if total_tokens > daily_token_limit:
        raise HTTPException(
                         status_code = 429,
                         detail = 'Daily token limit exhausted.',
                        )
    # reassign max_tokens
    # available_tokens = daily_limit - total_tokens(tokens_used + prompt_tokens)
    available_tokens = daily_token_limit - total_tokens
    # max_tokens = min(available_tokens,max_tokens)
    _max_tokens = min(available_tokens,_max_tokens)
    













