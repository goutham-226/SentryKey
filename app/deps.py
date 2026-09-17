from fastapi.security import HTTPBasic,HTTPBasicCredentials,HTTPBearer,HTTPAuthorizationCredentials
from fastapi import Depends,HTTPException
from app.models import Users,ApiKeys,Models,Subscriptions,SubscriptionTiers
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.security import verify_password
from app.schemas import ChatRequest
from sqlalchemy import *
from sqlalchemy.orm import *
import hashlib

basic = HTTPBasic()
bearer = HTTPBearer()

async def get_bearer_key(credentials: HTTPAuthorizationCredentials|None = Depends(bearer),db: AsyncSession = Depends(get_db),payload: ChatRequest) -> ApiKeys:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail='Unauthorized',
        )
    raw_key = credentials.credentials
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    stmt = select(ApiKeys).where(ApiKeys.key_hash == key_hash)
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.revoked_on is not None:
        raise HTTPException(
            status_code=401,
            detail='Unauthorized',
        )
    stmt = select(Users).where(
        Users.api_key_id == api_key.id,
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    stmt = select(Subscriptions.tier_id).where(
        Subscriptions.user_id == user.id,
        Subscriptions.period_end > func.now(),    
    )
    result = await db.execute(stmt)
    tier_id = result.scalar_one_or_none() # there is only one active subscription per user
    if tier_id is None:
        raise HTTPException(
            status_code=403,
            detail="user has no active subscriptions.",
        )
    stmt = select(Models).where(Models.model_id == payload.model)
    result = await db.execute(stmt)
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(
            status_code=404,
            detail='model not found',
        )
    stmt = select(SubscriptionTiers.rank).where(Subscriptions.id == tier_id)
    result = await db.execute(stmt)
    user_rank = result.scalar_one_or_none() # users tier rank if rank > than model's min_tier rank then user has privilige
    stmt = select(SubscriptionTiers.rank).where(Susbcriptions.id == model.min_tier_id)
    result = await db.execute(stmt)
    model_rank = result.scalar_one_or_none()
    if not user_rank >= model_rank:
        raise HTTPException(
            status_code=403,
            detail='user lacks privilige',
        )
    return api_key



async def get_current_user(credential: HTTPBasicCredential = Depends(basic),db: AsyncSession = Depends(get_db)) -> Users:
    email = credential.username
    password = credential.password
    stmt = select(Users).where(Users.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password,user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate" : "Basic"},
        )
    return user



