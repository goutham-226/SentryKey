from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, status, Depends
from app.schemas import UserCreate, UserOut, EchoRequest, EchoResponse, KeyOut, KeyCreate, UserCreated
from app.config import Settings, get_settings
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.models import Users, ApiKeys, UsageRecords
from pydantic import EmailStr
from sqlalchemy import select
import secrets
import hashlib

app = FastAPI(title="key & quota service",version="0.1.0")

@app.get("/health")
def health() -> dict[str,str]:
    return {"status":"ok"}

@app.post("/v1/users",response_model=UserCreated,status_code=status.HTTP_201_CREATED)
async def users(payload: UserCreate,db: AsyncSession = Depends(get_db)):
    user = Users(email=payload.email,name=payload.name)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409,detail="Email already registered")
    raw_key = "kq_" + secrets.token_urlsafe(24)
    prefix_key = raw_key[:11] 
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key = ApiKeys(user_id=user.id,key_prefix=prefix_key,key_hash=key_hash)
    db.add(key)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback() #set back to the prev stable state
        raise HTTPException(status_code=409,detail="Hashing Error")
    await db.refresh(user)
    user_created = UserCreated(
        id=user.id,
        email=user.email,
        name=user.name,
        created_on=user.created_on,
        api_key=raw_key,
    )
    return user_created
    
@app.get("/v1/users/{user_id}",response_model=UserOut)
async def get_users(user_id: int,db: AsyncSession = Depends(get_db)):
    user = await db.get(Users,user_id) # ret the row with the matching id
    if user is None:
        raise HTTPException(status_code=404,detail="Error User not found")
    return user

@app.post("/v1/echo",response_model=EchoResponse) #200 is default FastAPI status code for post
def echo(payload: EchoRequest, settings: Settings = Depends(get_settings)):
    request = payload.prompt
    reply = request[::-1] # rev the string str[start:stop:step]
    tokens = len(reply.split()) #returns the number of words(tokens)
    echo_ret = {
        "output": reply,
        "tokens_used": tokens,
        "quota": settings.default_monthly_quota,
    }
    return echo_ret


@app.post("/v1/keys",response_model=KeyOut,status_code=status.HTTP_201_CREATED)
async def create_key(payload: KeyCreate,db: AsyncSession = Depends(get_db)):
    user_email = payload.email
    stmt = select(Users).where(Users.email == user_email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none() # email is unique
    if user is None:
        raise HTTPException(status_code=404,detail="User Not Found")
    _user_id = user.id
    raw_key = "kq_" + secrets.token_urlsafe(24)
    key_prefix = raw_key[:11]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key = ApiKeys(user_id = _user_id,key_prefix =key_prefix,key_hash=key_hash)
    db.add(key)
    await db.commit()
    await db.refresh(key)
    key_created = KeyOut(
        id = key.id,
        user_id = key.user_id,
        monthly_quota = key.monthly_quota,
        revoked_on = key.revoked_on,
        created_on = key.created_on,
        api_key = raw_key,
    )
    return key_created








