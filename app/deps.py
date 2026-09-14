from fastapi.security import HTTPBasic,HTTPBasicCredentials
from fastapi import Depends,HTTPException
from app.models import Users,ApiKeys
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.security import verify_password

basic = HTTPBasic()

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



