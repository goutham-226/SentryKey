# tests/test_keys.py

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




   


   
   













































