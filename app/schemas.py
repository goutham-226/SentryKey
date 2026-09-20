from datetime import datetime
from typing import Literal
from pydantic import BaseModel,EmailStr,Field

class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1,max_length=100)
    password: str = Field(min_length=8,max_length=27)
 
class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    created_on: datetime

class KeyCreate(BaseModel):
    email: EmailStr
    password: str

class KeyOut(BaseModel):
    daily_quota: int
    api_key: str

class PublicCatalog(BaseModel):
    model_name: str
    provider: str
    tier: str

class UserSubscribe(BaseModel):
    tier: str
    period_end: datetime

class SubscribeCatalog(BaseModel):
    tier: Literal["Basic","Pro","Premium"]

class ChatRequest(BaseModel):
    prompt: str
    model: str
    max_tokens: int
    conversation_id: int | None
  

class ChatResponse(BaseModel):
    model: str
    output: str
    prompt_tokens: int
    completion_tokens: int
    quota_remaining: int
    conversation_id: int
    error_detail: str | None










