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
from decimal import Decimal

app = FastAPI(title="key & quota service",version="0.1.0")


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
async def chat_completions(payload: ChatRequest,user_model: Models = Depends(get_bearer_key),db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)):
    # add privilige check within get_bearer_key 
    # pass api_key to service
   
    

'''
/v1/chat/completions is the first version of the endpoint
this will eventually be cleaned up with separate service modules
and privilige access embeded into get_key function.
'''















     




