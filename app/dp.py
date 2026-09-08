from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession,create_async_engine,async_sessionmaker
from app.config import get_settings

settings = get_settings()

# create an engine to open a connection pool
# flags echo=False do not want sqlalchemy to print sql statements on the terminal
# pool_pre_ping=True check the liveness of the connection pool

engine = create_async_engine(settings.database_url,echo=False,pool_pre_ping=True)

#create a session maker -> an instance of a session [a session is the one making the actuall connection]

SessionLocal = async_sessionmaker(engine,class=AsyncSession,exit_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession,None]:
    async with SessionLocal() as session:
        yield session

