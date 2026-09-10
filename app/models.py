'''
* convert our existing SQL into object relational mapping using sqlalchemy
*
'''
from datetime import datetime
from sqlalchemy import *
from sqlalchemy.orm import *
      
class Base(DeclarativeBase): # one instance to hold all the metadata for accurate schema
    pass

class Users(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    email: Mapped[str] = mapped_column(Text,unique=True)
    name: Mapped[str] = mapped_column(Text)
    created_on: Mapped[datetime] = mapped_column(server_default=func.now())
    api_key: Mapped[list["ApiKeys"]] = relationship(back_populates="user",cascade="all, delete-orphan")

class ApiKeys(Base):
    __tablename__ = 'api_keys'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("users.id",ondelete="CASCADE"))
    key_prefix: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(Text,unique=True)
    monthly_quota: Mapped[int] = mapped_column(BigInteger,server_default="100000")
    revoked_on: Mapped[datetime|None]
    created_on: Mapped[datetime] = mapped_column(server_default=func.now())
    user: Mapped["Users"] = relationship(back_populates='api_key')

class UsageRecords(Base):
    __tablename__ = 'usage_records'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    api_key_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("api_keys.id",ondelete='CASCADE'))
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    token_count: Mapped[int] = mapped_column(BigInteger)
    status_code: Mapped[int] = mapped_column(SmallInteger)
    latency_ms: Mapped[int] = mapped_column(Integer)






