from datetime import datetime
from pydantic import BaseModel,EmailStr,Field,SecretStr

class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1,max_length=100)
    password: SecretStr = Field(min_length=8,max_length=100)
 
class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    created_on: datetime

class KeyCreate(BaseModel):
    email: EmailStr
    password: SecretStr

class KeyOut(BaseModel):
    dail_quota: int
    api_key: str

class PublicCatalog(BaseModel):
    model_name: str
    provider: str
    tier: str