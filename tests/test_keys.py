# tests/test_keys.py

# pytest.raises to catch HTTPExceptions
import pytest

# get_bearer_key() and bearer_auth() dependencies.
from app.deps import get_bearer_key, bearer_auth
# database session
from app.db import SessionLocal
# ChatRequest BaseModel to pass into get_bearer_key
from app.schemas import ChatRequest 

# fastapi
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

"""
Test if POST /v1/keys returns 201 and a
key on valid request.

Test if POST /v1/keys returns 401
on requests with a worng password.

Test is POST /v1/Keys returns 401
on requests with an unknown email.
 
"""
async def test_post_v1_keys_returns_a_key_and_201(client,user):
    email = user['email']
    password = user['password']
    
    request = {'email':email, 'password':password}
    response = await client.post('/v1/keys',json=request)
    body = response.json()
    
    assert response.status_code == 201
    assert 'api_key' in body
    assert 'key_id'  in body
   
    # create a response with a wrong password
    request = {'email':email,'password':'wrong_password'}
    response = await client.post('/v1/keys',json=request)
    
    assert response.status_code == 401

    # create a response with an registered email
    request = {'email':'unknown@email.com','password':'123456789'}
    response = await client.post('/v1/keys',json=request)
    
    assert response.status_code == 401
# func end tables are truncated


"""
Test if GET /v1/keys returns only key-prefix,
and never the full keys.
"""
async def test_get_v1_keys_only_returns_prefix(client,user):
    email = user['email']
    password = user['password']
    
    #create an api_key using POST /v1/keys
    request = {'email':email,'password':password}
    response = await client.post('/v1/keys',json=request)
    body = response.json()
    raw_key = body['api_key']
   
    #get an api_key 
    response = await client.get('/v1/keys',auth=(email,password))
    body = response.json()
    body = body[0]
    api_key = body['api_key']
   
    assert raw_key[:11] == api_key
    assert 'key_id' in body

"""
Test if GET /v1/keys returns 401
on Bad credentials.
"""
async def test_get_v1_keys_returns_401_on_bad_credentials(client):
    email = 'unknown@email.com'
    password = 'password'

    response = await client.get('/v1/keys',auth=(email,password))
    
    assert response.status_code == 401

"""
Test if GET /v1/keys
returns 404 when a user did not generate any keys.
"""
async def test_get_v1_keys_returns_404_when_user_has_not_generated_a_key(client,user):
    email = user['email']
    password = user['password']
   
    # do not create a key send a request to GET /v1/keys
    response = await client.get('/v1/keys',auth=(email,password))
    
    assert response.status_code == 404

"""
Test if DELETE /v1/keys/{key_id}
returns success and 200.
"""
async def test_revoke_keys_returns_200_on_success(client,user):
    # create an api_key
    email = user['email']
    password = user['password']
   
    # POST /v1/keys takes in email and password as input params.
    request = {'email':email,'password':password} 
    response = await client.post('/v1/keys',json=request)
    
    assert response.status_code == 201
    body = response.json()
  
    # get the key_id
    key_id = body['key_id']
    
    # revoke the key using DELETE /v1/keys/{key_id}
    response = await client.delete(f'/v1/keys/{key_id}',auth=(email,password))
    body = response.json()    
 
   
    assert body['status'] == 'success'

"""
Test if revoking a non existent key returns a 404.
"""
async def test_revoke_key_raises_404_on_non_existing_key(client,user):
    # do not create an api_key
    key_id = 5 # random key_id, Tables are truncated with Restart identity cascade after every test function run.
    response = await client.delete(f'/v1/keys/{key_id}',auth=(user['email'],user['password']))
    
    assert response.status_code == 404


"""
Test if GET /v1/keys raises 404,
when all keys are revocked.
"""
async def test_get_keys_raises_404_when_keys_are_revoked(client,user):
    # create api_key
    email = user['email']
    password = user['password']
    
    # send a req to POST /v1/keys
    request = {'email':email,'password': password}
    response = await client.post('/v1/keys',json=request)
    assert response.status_code == 201
    body = response.json()

    key_id = body['key_id']

    # delete the key.
    response = await client.delete(f'/v1/keys/{key_id}',auth=(email,password))
    
    # send a request to GET /v1/keys
    response = await client.get('/v1/keys',auth=(email,password))
    
    assert response.status_code == 404

"""
Test if revoking with bad credentials
raises 401.

User authentication is processed before
keys are checked - so on wrong credentioals with a non-existant key_id
it should raise 401.
"""
async def test_if_revoke_keys_with_bad_credentials_raise_401(client):
     response = await client.delete(f'/v1/keys/{1}',auth=('email','password'))
     
     assert response.status_code == 401





"""
Test if revoking with other users credentials
raises 404.
"""

async def test_revoke_keys_with_other_users_credentials_raises_401(client,user):
    # create a key for user
    response = await client.post('/v1/keys',json={'email':user['email'],'password':user['password']})
    assert response.status_code == 201
    key_id = response.json()['key_id']
    
    # create a new user
    new_user = {'email':'new_1@email.com','name':'new_1','password':'password'}
    response = await client.post('/v1/auth/register',json=new_user)
    assert response.status_code == 201 # new user created   

    # create a new key for the new user
    response = await client.post('/v1/keys',json={'email':new_user['email'],'password':new_user['password']})
    assert response.status_code == 201
    new_key_id = response.json()['key_id']
   
    # revoke
    response = await client.delete(f'/v1/keys/{key_id}',auth=(new_user['email'],new_user['password']))
    
    assert response.status_code == 404

"""
Test if get_bearer_key raises 401 on a deleted key.

- create key
- get raw_key 
- get key_id
- delete key
- send req to get_bearer_key
- assert 401

"""
async def test_get_bearer_key_raises_404_on_deleted_key(client,subscribed_user):
    # create a key
    user = await subscribed_user('Basic')
    email = user['email']
    password = user['password']
  
    # send a post request
    request = {'email':email,'password':password} 
    response = await client.post('/v1/keys',json=request)
   
    assert response.status_code == 201
    
    body = response.json()
    raw_key = body['api_key']
    key_id = body['key_id']

    # delete key
    response = await client.delete(f'/v1/keys/{key_id}',auth=(email,password))
    
    # assert success 
    assert response.status_code == 200
   
    payload = ChatRequest(
                prompt='fake prompt',
                model='gpt-5.6-luna',
                max_tokens=100,
              ) 
                
    creds = HTTPAuthorizationCredentials(scheme='Bearer', credentials=raw_key)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as e:
            await get_bearer_key(payload=payload,credentials=creds,db=db)
   
  
    assert e.value.status_code == 401































     





 
















    


   


