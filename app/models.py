from datetime import datetime
from sqlalchemy import *
from sqlalchemy.orm import *
from decimal import Decimal
      
class Base(DeclarativeBase): # one instance to hold all the metadata for accurate schema
    pass

class Users(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    email: Mapped[str] = mapped_column(Text,unique=True)
    name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    created_on: Mapped[datetime] = mapped_column(server_default=func.now())
    api_key: Mapped[list["ApiKeys"]] = relationship(back_populates="user",cascade="all, delete-orphan") # a single user can have 1+ keys
    subscription: Mapped[list["Subscriptions"]] = relationship(back_populates='user',cascade='all, delete-orphan')

class ApiKeys(Base):
    __tablename__ = 'api_keys'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("users.id",ondelete="CASCADE"))
    key_prefix: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(Text,unique=True)
    daily_quota: Mapped[int] = mapped_column(BigInteger,server_default="100000")
    revoked_on: Mapped[datetime|None]
    created_on: Mapped[datetime] = mapped_column(server_default=func.now())
    user: Mapped["Users"] = relationship(back_populates='api_key')
    conversation: Mapped[list['Conversations']] = relationship(back_populates='api_key', cascade='all, delete-orphan')	

class UsageRecords(Base):
    __tablename__ = 'usage_records'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    api_key_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("api_keys.id",ondelete='CASCADE'))
    model_id: Mapped[int|None] = mapped_column(BigInteger,ForeignKey('models.id',ondelete='SET NULL'))
    conversation_id: Mapped[int|None] = mapped_column(BigInteger,ForeignKey('conversations.id',ondelete='SET NULL'))
    prompt_tokens: Mapped[int] = mapped_column(BigInteger)
    completion_tokens: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    status_code: Mapped[int] = mapped_column(SmallInteger)
    latency_ms: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal|None] = mapped_column(Numeric(12,6))

class SubscriptionTiers(Base):
    __tablename__ = 'subscription_tiers'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    rank: Mapped[int] = mapped_column(SmallInteger)
    daily_quota: Mapped[int] = mapped_column(Integer,server_default="100000")
    created_on: Mapped[datetime] = mapped_column(server_default=func.now())
    model: Mapped[list["Models"]] = relationship(back_populates='tiers')
    subscription: Mapped[list["Subscriptions"]] = relationship(back_populates='tier')

class Models(Base):
    __tablename__ = 'models'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    model_id: Mapped[str] = mapped_column(Text,unique=True)
    provider: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    min_tier_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('subscription_tiers.id'))
    tiers: Mapped['SubscriptionTiers'] = relationship(back_populates='model')
    context_window: Mapped[int] = mapped_column(Integer)
    input_price_per_1M: Mapped[Decimal] = mapped_column(Numeric(12,6))
    output_price_per_1M: Mapped[Decimal] = mapped_column(Numeric(12,6))
    is_active: Mapped[bool] = mapped_column(Boolean,server_default='true') # to raise model not available when provider depricates    
    created_on: Mapped[datetime] = mapped_column(server_default=func.now())

class Conversations(Base):
    __tablename__ = 'conversations'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    api_key_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('api_keys.id',ondelete='CASCADE'))
    title: Mapped[str] = mapped_column(Text)
    created_on: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_on: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_on: Mapped[datetime|None]
    api_key: Mapped['ApiKeys'] = relationship(back_populates='conversation')
    message: Mapped[list['Messages']] = relationship(back_populates='conversation',cascade='all, delete-orphan')
    
class Messages(Base):
    __tablename__ = 'messages'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('conversations.id',ondelete='CASCADE'))
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    created_on: Mapped[datetime ] = mapped_column(server_default=func.now())
    conversation: Mapped['Conversations'] = relationship(back_populates='message')


class Subscriptions(Base):
    __tablename__ = 'subscriptions'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('users.id',ondelete='CASCADE'))
    tier_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('subscription_tiers.id',ondelete='CASCADE'))
    status: Mapped[str] = mapped_column(Text)
    period_start: Mapped[datetime] = mapped_column(Datetime) # business fact dont set it to server default 
    period_end: Mapped[datetime] = mapped_column(DateTime)
    created_on: Mapped[datetime] = mapped_column(server_default=func.now())
    user: Mapped["Users"] = relationship(back_populates='subscription')
    tier: Mapped["SubscriptionTiers"] = relationship(back_populates='subscription')

























