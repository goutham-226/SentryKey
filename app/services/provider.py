from app.config import get_settings
from replicate.client import Client
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select, text, Date
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import SessionLocal
from app.models import Users, ApiKeys, UsageRecords, Models, SubscriptionTiers, Subscriptions, Messages, Conversations
from fastapi import HTTPException
from app.schemas import ChatRequest, ChatResponse

settings = get_settings()
client = Client(api_token=settings.replicate_api_token)

async def  get_response(api_key: ApiKeys, payload: ChatRequest) -> ChatResponse:
    #api_key is authorized
    #model and tier are checked
    async with SessionLocal as db:
        stmt = select(Models).where(Models.model_is == payload.model)
        result = await db.execute(stmt)
        model = result.scalar_one_or_none()
        max_tkn_schema = model.max_token_schema
        prompt = payload.prompt
        max_tokens = payload.max_tokens
        #check quota balance
        stmt = select(func.sum(UsageRecords.prompt_tokens + UsageRecords.completion_tokens)).where(
            UsageRecords.api_key_id == api_key.id,
        )
        result = await db.execute(stmt)
        total_ledger_sum = result.scalar()
        if total_ledger_sum is None:
        total_ledger_sum = 0
        prompt_tokens = len(prompt.split())
        if (total_ledger_sum + prompt_tokens) >= api_key.daily_quota:
            raise HTTPException(
                status_code=429,
                detail='quota limit exceeded',
            )
        remaining_quota = api_key.daily_quota - (total_ledger_sum + prompt_tokens)
        max_tokens = min(max_tokens,remaining_quota)
        
        
         
