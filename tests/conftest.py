# tests/config.py

import os

# set your test database url
os.environ["DATABASE_URL"] = "postgresql+asyncpg://kq:kq@localhost:5432/sk_test"

# import pytest dependencies
import pytest
from httpx import AsyncClient, ASGITransport
from alembic import command
from alembic.config import Config
from sqlalchemy import text

#import dependencies from app
from app.main import app
from app.db import engine

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
"""

@pytest.fixture(scope="session",autouse=True)
def upgrade_migrations():
     # load alembic.ini -> it finds our migrations directory 
     alembic_config = Config("alembic.ini")
     #upgrade head using command
     command.upgrade(alembic_config,"head")
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
















            







































 
