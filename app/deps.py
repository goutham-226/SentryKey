from fastapi.security import HTTPBasic,HTTPBasicCredentials,HTTPBearer,HTTPAuthorizationCredentials
from fastapi import Depends,HTTPException
from app.models import Users,ApiKeys
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.security import verify_password
from sqlalchemy import *
from sqlalchemy.orm import *
import hashlib

basic = HTTPBasic()
bearer = HTTPBearer()

async def get_bearer_key(credentials: HTTPAuthorizationCredentials|None = Depends(bearer), db: AsyncSession = Depends(get_db)) -> ApiKeys:
    if credentials is None:
        raise HTTPException(
            status=401,
            detail='Unauthorized',
        )
    raw_key = credentials.credentials
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    stmt = select(ApiKeys).where(ApiKeys.key_hash == key_hash)
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.revoked_on is not None:
        raise HTTPException(
            status=401,
            detail='Unauthorized',
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



