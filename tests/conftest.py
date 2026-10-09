# tests/config.py

import os
import asyncio 

# set your test database url
os.environ["DATABASE_URL"] = "postgresql+asyncpg://kq:kq@localhost:5432/sk_test"
#add a placeholder key for OPEN_AI_API_KEY
os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"

# import pytest objects
import pytest
from httpx import AsyncClient, ASGITransport
from alembic import command
from alembic.config import Config
from sqlalchemy import text

#import app objects
from app.main import app
from app.db import engine

# import model seed script 
from scripts.model_seed import seed

"""
Pytest:
======

@pytest.fixture creates setup and teardown functions for your tests

scope decides when our fixture runs:

example:
------
scope="function" -> runs once per test function
scope="session" -> runs for the entire test session

here we are updating our alembic configuration with our test_db url -> we need it once per session

a fixture doesnt run unless it is called as an argument by another test method 
using autouse=True will force a fixture to execute within it's scope
without being called by any function.  

method upgrade_migrations updates our alembic/env.py with our test db url

every thing before yield is ran before any test function,
we want our database url to be updated before any test function 
ever runs to avoid making changes to our main database.

Seed your model Tables with models from your scripts folder.
-> import the function and run it.

"""

async def seed_wrapper():
    async with engine.begin() as db:
        await db.execute(text('TRUNCATE models RESTART IDENTITY CASCADE'))
    await seed()
    await engine.dispose()

@pytest.fixture(scope="session",autouse=True)
def upgrade_migrations():
     # load alembic.ini -> it finds our migrations directory 
     alembic_config = Config("alembic.ini")
     #upgrade head using command
     command.upgrade(alembic_config,"head")
     # upgrade alembic with new db url
     # now seed your models table
     asyncio.run(seed_wrapper())
     yield


"""
Clean the database after every test:

- remove any new users
- remove any new api_keys
- remove any new subscriptions
- remove any new messages and conversations
- rmove usage records 

do not remove  models and subscritpion Tiers - migrations are updatyyed only once per
test session.

PostgreSQL:

TRUNCATE table_name
RESTART IDENTITY CASCADE; -> resets id to 0 for every table
"""
# Clean Database after every test
@pytest.fixture(autouse=True) # default scope is function
async def clean_db():
    yield # run the tests
    async with engine.begin() as session:
        await session.execute(
            text(""" TRUNCATE
		     users,
		     api_keys,
		     conversations,
		     messages,
		     subscriptions,
		     usage_records
		   RESTART IDENTITY CASCADE 
                """)
            )
        # eninge.begin() auto commits your changes        
    await engine.dispose() # closes connection
"""
Httpx:
====
A standard python3 HTTP client library,
with both synchronous and asynchronous request handling.

AsyncClient:
-----------
An Instance of an object that sends
asynchronous requests to anything on the web.

ASGITransport:
------------
ASGI - Asynchronous Sever Gateway Instance.

By default an HTTP Client sends a request to a remote server,
but adding an ASGI transport object enables our Client to send 
requests directly to our ASGI app (FastAPI app)
 
"""
# create http async client
@pytest.fixture  # default session - function not auto use only runs when called by a test function
async def client():
    #create an ASGITransport obj
    transport = ASGITransport(app=app)
    # create an async client
    async with AsyncClient(transport=transport,base_url='http://test') as client:
        yield client # send the client to the caller function and wait while it runs

"""
Add a fixture, with function scope to
register a User to test other endpoints.
"""
@pytest.fixture
async def user(client):
    credentials = {'email':'test_user@email.com','name':'test_user','password':'password12345'}
    response = await client.post('/v1/auth/register',json=credentials)
    assert response.status_code == 201
    return credentials

"""
Add a fixture, with function scope to
create an api_key to test other endpoints.
"""
@pytest.fixture
async def api_key(client,user):
    email = user['email']
    password = user['password']
    
    # create an api_key
    request = {'email':email,'password':password}
    response = await client.post('/v1/keys',json=request)
    body = response.json()
    raw_key = body['api_key']
    
    return raw_key

"""
Add fixture for subscriped_user.
"""
@pytest.fixture
def subscribed_user(client):
    async def _subscribed_user(tier: str):
        # register a new user
        email = 'user@email.com'
        name = 'user'
        password = 'password123'
        credentials = {'email':email,'name':name,'password':password}
        response = await client.post('/v1/auth/register',json=credentials)
        
	# subscribe to 'tier' with user creds
        request = {'tier':tier}
        response = await client.post('/v1/subscriptions',json=request,auth=(email,password))
        
        return credentials
    return _subscribed_user

"""
A fixture to return, a subscribed api_key,
to use for calling /v1/chat/completions & /v1/chat-history/{conversation_id}.

"""
@pytest.fixture
def subscribed_api_key(client,subscribed_user):
    async def _subscribed_api_key(tier: str):
        user = await subscribed_user(tier=tier)
    
        email = user['email']
        password = user['password']
    
        # create an api_key
        request = {'email':email,'password':password}
        response = await client.post('v1/keys',json=request)
    
        assert response.status_code == 201
    
        return response.json()
    return _subscribed_api_key


































            







































 
