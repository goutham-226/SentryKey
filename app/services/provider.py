from datetime import timedelta
from typing import Any
from app.config import get_settings
from replicate.client import Client
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk, ChatCompletionMessageParam
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select, text, Date
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import SessionLocal
from app.models import Users, ApiKeys, UsageRecords, Models, SubscriptionTiers, Subscriptions, Messages, Conversations
from fastapi import HTTPException
from app.schemas import ChatRequest, ChatResponse

settings = get_settings()
replicate_client = Client(api_token=settings.replicate_api_token)
open_ai_client = AsyncOpenAI(api_key=settings.openai_api_key)

async def open_ai(payload: ChatRequest, chat_history: list[dict[str,str]] | None) -> ChatCompletion:
    if history is None:
        try:
            response = await client.chat.completions.create(
                model=payload.model,
                stream=False,
            )
        except 
    else:
        response = await client.chat.completions.create(
            model=payload.model,
            messages=chat_history,
            stream=False,
        )
    return response


async def  get_response(api_key: ApiKeys, payload: ChatRequest) -> ChatResponse:  #api_key is authorized, model and tier are checked
    async with SessionLocal as db:
        input_tokens = len(payload.prompt.split())
        #get model with model_id == payload.model to check provider and for usage records 
        stmt = select(Models).where(Models.model_id == payload.model)
        result = await db.execute(stmt)
        model = result.scalar_one_or_none()
        #check quota balance and adjust max-tokens
        stmt = select(func.sum(UsageRecords.prompt_tokens + UsageRecords.completion_tokens)).where(
                UsageRecords.api_key_id = api_key.id,
                UsageRecords.requested_at > func.now() - timedelta(days=1),
            )
        result = await db.execute(stmt)
        token_ledger_sum = result.scalar()
        if token_ledger_sum >= api_key.daily_quota or token_ledger_sum + input_tokens >= api_keys.daily_quota:
            raise HTTPException(
                status_code=429,
                detail="quota limit exceeded",
            )
        quota_remaining = (token_ledger_sum + input_tokens) - api_key.daily_quota
        max_tokens = min(payload.max_tokens,quota_remaining)
        payload.max_tokens = max_tokens
        if payload.conersation_id is not None:
            #create a list[dict[str,str]] to pass in as chat history
            stmt = select(Messages).where(Messages.conversation_id == )
    #check model_provider and pass it to its func
    if model.provider == 'openai':  
        if payload.conversation_id is None:
            output = await open_ai(payload) # get chat response
            output_text = output.choices[0].message.content or ""
            usage = output.usage
            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens
                
                
            

        

        
        
         
