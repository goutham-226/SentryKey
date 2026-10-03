# tests/test_deps.py

# Test authorization dependencies.

"""
Test if get_curerent_user raises
401 on missing credentials.

send a req to GET /v1/keys without an auth head,
and assert status_code 401.

user check happens before querying an api_key from
the database - so the function does not create an api_key using POST /v1/keys
for this test.
"""
async def test_get_current_user_raises_401_on_no_credentials(client):
    response = await client.get('/v1/keys') # no auth header
    
    assert response.status_code == 401

"""
Test if get_current_user raise
401 on unknown user.

call GET /v1/keys with an unregistered user.
"""
async def test_get_current_user_raises_401_on_unknown_user(client):
    # create fake credentials
    email = 'user@example.com'
    password = 'password123'

    # send a request
    response = await client.get('/v1/keys',auth=(email,password))
   
    # assert 401
    assert response.status_code == 401


"""
Test if get_bearer_key raises 401
with a missing  Authorization header.

send a request to /v1/chat/completions with missihg header,
and assert if status code is 401.
"""
async def test_get_bearer_key_raises_401_on_no_auth_header(client):
    request = {'prompt':'prompt ',
               'model':'gpt-5.6-luna',
               'max_tokens':500,
              }
    response = await client.post('/v1/chat/completions',json=request)
    
    assert response.status_code == 401

"""
Test if bearer_auth raises 401,
on missing header use endpoint,
GET /v1/chat-history/{conversation_id}.

Auth check happens before querying conversation rows in the
database, so use a placeholder value to pass into {conversation_id}.

"""
async def test_bearer_auth_raises_401_on_no_auth_header(client):
    conversation_id = 3
   
    response = await client.get(f'/v1/chat-history/{conversation_id}') # missing auth header.
   
    assert response.status_code == 401










































