from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, status, Depends, Header
from app.schemas import UserCreate, UserOut, KeyOut, KeyCreate, PublicCatalog, UserSubscribe, SubscribeCatalog, ChatRequest, ChatResponse
from app.config import Settings, get_settings
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.models import Users, ApiKeys, UsageRecords, Models, SubscriptionTiers, Subscriptions, Messages, Conversations
from pydantic import EmailStr,SecretStr
from sqlalchemy import func, select, update, text, Date
import secrets
import hashlib
from app.security import hash_password,verify_password
from app.deps import get_current_user, get_bearer_key
from replicate.client import Client
from decimal import Decimal

app = FastAPI(title="key & quota service",version="0.1.0")
client = Client(api_token=get_settings().replicate_api_token)

@app.get("/health")
def health() -> dict[str,str]:
    return {"status":"ok"}

@app.post("/v1/auth/register",response_model=UserOut,status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate,db: AsyncSession = Depends(get_db)):
    print(len(payload.password))
    password = hash_password(payload.password)
    user = Users(email=payload.email,name=payload.name,password_hash=password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409,detail="Email already registered")
    await db.refresh(user)
    user_created = UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        created_on=user.created_on,
    )
    return user_created

@app.post("/v1/keys",response_model=KeyOut,status_code=status.HTTP_201_CREATED) 
async def create_key(payload:KeyCreate,db: AsyncSession = Depends(get_db)):
    stmt = select(Users).where(Users.email == payload.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password,user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )
    raw_key = "kq_" + secrets.token_urlsafe(24)
    key_prefix = raw_key[:11]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    apikey = ApiKeys(user_id=user.id,key_prefix=key_prefix,key_hash=key_hash)
    db.add(apikey)
    try:
        await db.commit()
    except IntegrityError:
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error",
        )
        await db.rollback()
    await db.refresh(apikey)
    key_out = KeyOut(
        daily_quota=apikey.daily_quota,
        api_key=raw_key,
    )
    return key_out

@app.get("/v1/models-catalog",response_model=list[PublicCatalog]) # default 200
async def display_models(db: AsyncSession = Depends(get_db)):
    stmt = select(Models)
    result = await db.execute(stmt)
    model = result.scalars().all()
    public_catalog = []
    for m in model:
        stmt = select(SubscriptionTiers).where(SubscriptionTiers.id == m.min_tier_id)
        result = await db.execute(stmt)
        tier = result.scalar()
        catalog = PublicCatalog(
            model_name=m.model_id,
            provider=m.provider,
            tier=tier.name,
        )
        public_catalog.append(catalog)
    return public_catalog

@app.get("/v1/keys",response_model=list[KeyOut])
async def get_keys(user: Users = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(ApiKeys).where(ApiKeys.user_id == user.id)
    result = await db.execute(stmt)
    apikey = result.scalars().all()
    if apikey is None:
        raise HTTPException(
            status_code=404,
            detail="No API keys Found",
        )
    key_out = []
    for key in apikey:
        out = KeyOut(
            daily_quota= key.daily_quota,
            api_key= key.key_prefix,
        )
        key_out.append(out)
    return key_out

@app.post('/v1/subscriptions',response_model=UserSubscribe,status_code=status.HTTP_201_CREATED)
async def subscribtions(payload: SubscribeCatalog,user: Users = Depends(get_current_user),db: AsyncSession = Depends(get_db)):
    #401 is already raised if credentials are wrong by get_current_user
    tier_name = payload.tier
    stmt = select(SubscriptionTiers).where(SubscriptionTiers.name == tier_name)
    result = await db.execute(stmt)
    tier = result.scalar_one_or_none()
    if tier is None:
        raise HTTPException(
            status_code=500,
            detail="Database Seed Fail!"
        )
    stmt = select(Subscriptions.id).where(
        Subscriptions.user_id == user.id,
        func.now().between(Subscriptions.period_start,Subscriptions.period_end),
        )
    result = await db.execute(stmt)
    sub = result.scalar_one_or_none() # only one row exists with an ective subscription between start and end
    if sub is not None:
        raise HTTPException(
            status_code=409,
            detail='Subscription Already exists!'
        )
    subscription = Subscriptions(
        user_id = user.id,
        tier_id = tier.id,
        status = "active",
        period_start = func.now(),
        period_end = func.now() + text("interval '1 month'")
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    user_subscribe = UserSubscribe(
        tier = tier.name,
        period_end=subscription.period_end,
    )
    return user_subscribe
    

@app.post('/v1/chat/completions',response_model=ChatResponse) # default status - 200 OK
async def chat_completions(payload: ChatRequest,api_key: ApiKeys = Depends(get_bearer_key),db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    stmt = select(Users).where(Users.id == api_key.user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    stmt = select(Subscriptions.tier_id).where(
        Subscriptions.user_id == user.id,
        Subscriptions.period_end > func.now()
    )
    result = await db.execute(stmt)
    tier_id = result.scalar_one_or_none()
    if tier_id is None:
        raise HTTPException(
            status_code=403,
            detail="User Has no active Subscriptions",
        )
    stmt = select(Models).where(Models.min_tier_id == tier_id,Models.model_id == payload.model)
    result = await db.execute(stmt)
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(
            status_code=403,
            detail="Model not available or User lacks privilige"
        )
    prompt = payload.prompt
    max_tokens = payload.max_tokens
    stmt = select(func.sum(UsageRecords.completion_tokens + UsageRecords.prompt_tokens)).where(
        UsageRecords.api_key_id == api_key.id,
        UsageRecords.requested_at >= func.date_trunc('day',func.now()),
    )
    result = await db.execute(stmt)
    token_ledger_sum = result.scalar()
    if token_ledger_sum is None:
        token_ledger_sum = 0
    if token_ledger_sum is not None and token_ledger_sum > api_key.daily_quota :
        raise HTTPException(
            status_code=429,
            detail='Quota Exceeded',
        )
    if token_ledger_sum + len(prompt.split()) > api_key.daily_quota:
        raise HTTPException(
            status_code=429,
            detail='Quota Exceeded',
        )
    quota_remaining = api_key.daily_quota - (token_ledger_sum + len(prompt.split()))
    max_tokens = min(max_tokens,quota_remaining)
    # after this check max_tokens cannot be zero because we've taken into account prompt tokens exceeding quota
    max_tokens_str = ''
    provider_name = payload.model.split('/')
    company = provider_name[0]
    if company == 'google':
        max_tokens_str = 'max_output_tokens'
    elif company == 'openai':
        max_tokens_str = 'max_completion_tokens'
    elif company == 'meta':
        max_tokens_str = 'max_new_tokens'
    else:
        max_tokens_str = 'max_tokens'
    model_input = {
        "prompt": prompt,
        max_tokens_str: max_tokens,
    }
    prediction = await client.predictions.async_create(
        model=payload.model,
        input=model_input,
    )
    await prediction.async_wait()
    output = "".join(prediction.output or [])
    output_tokens = prediction.metrics.get("token_output_count",0)
    prompt_tokens = prediction.metrics.get("token_input_count",0)
    conversation_id = 0
    if payload.conversation_id is None:
        conversation = Conversations(
            api_key_id = api_key.id,
            title = output[:11],
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        conversation_id = conversation.id
    else:
        stmt = select(Conversations).where(Conversations.id == payload.conversation_id, Conversations.api_key_id == api_key.id)
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation is None:
            new_conversation = Conversations(
                api_key_id = api_key.id,
                title = output[:11],
            )
            db.add(new_conversation)
            await db.commit()
            await db.refresh(new_conversation)
            conversation_id = new_conversation.id
        else:
            conversation_id = payload.conversation_id
    #create user_message_row
    message = Messages(
        conversation_id = conversation_id,
        role = 'User',
        content = prompt,
        token_count = prompt_tokens,
    )
    db.add(message)
    await db.flush()
    #create assistant_message_row
    message = Messages(
        conversation_id = conversation_id,
        role = 'Assistant',
        content = output,
        token_count = output_tokens,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    input_price = model.input_price_per_1M * ((len(prompt.split()))/Decimal(1000000))
    out_price = model.output_price_per_1M * ((output_tokens)/Decimal(1000000))
    cost = input_price + out_price
    usage_records = UsageRecords(
        api_key_id = api_key.id,
        model_id = model.id,
        conversation_id = conversation_id,
        prompt_tokens = prompt_tokens,
        completion_tokens = output_tokens,
        status = "complete",
        status_code = 200,
        latency_ms = int(prediction.metrics["total_time"] * 1000),
        cost_usd = cost,
    )
    db.add(usage_records)
    await db.commit()
    await db.refresh(usage_records)
    stmt = select(func.sum(UsageRecords.prompt_tokens + UsageRecords.completion_tokens)).where(
        UsageRecords.api_key_id == api_key.id,
        UsageRecords.requested_at >= func.date_trunc('day',func.now()),
    )
    result = await db.execute(stmt)
    total_ledger_sum = result.scalar()
    quota_remaining = api_key.daily_quota - total_ledger_sum
    chat_response = ChatResponse(
        model=model.model_id,
        output=output,
        prompt_tokens=len(prompt.split()),
        completion_tokens=output_tokens,
        quota_remaining = quota_remaining,
        conversation_id = conversation_id,
    )
    return chat_response
    

'''
/v1/chat/completions is the first version of the endpoint
this will eventually be cleaned up with separate service modules
and privilige access embeded into get_key function.
'''















     




