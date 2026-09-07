from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, status, Depends
from app.schemas import UserCreate, UserOut, EchoRequest, EchoResponse
from app.config import Settings, get_settings

app = FastAPI(title="key & quota service",version="0.1.0")

_users: dict[int,UserOut] = {} # maps an id to a user (UserOut) class type
_next_id: int = 1 # key value to map UserOut objects 

@app.get("/health")
def health() -> dict[str,str]:
    return {"status":"ok"}

@app.post("/v1/users",response_model=UserOut,status_code=status.HTTP_201_CREATED)
def users(payload: UserCreate):
    global _next_id # to avoid local variable assignment
    global _users
    for u in _users.values():
        if u.email == payload.email:
            raise HTTPException(status_code=409,detail="email already registered")
    user = {
        "id": _next_id,
        "email": payload.email,
        "name": payload.name,
        "created_on": datetime.now(timezone.utc),
    }
    _users[_next_id] = user
    _next_id += 1
    return user

@app.get("/v1/users/{user_id}",response_model=UserOut)
def get_user(user_id: int):
    user = _users[user_id]
    if user is None:
        raise HTTPException(status_code=401,detail="user not found")
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











