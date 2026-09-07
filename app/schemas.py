from datetime import datetime
from pydantic import BaseModel,EmailStr,Field

class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1,max_length=100)

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    created_on: datetime

class EchoRequest(BaseModel):
    prompt: str = Field(min_length=1,max_length=8000)
 
class EchoResponse(BaseModel):
    output: str
    tokens_used: int
    quota: int
 
