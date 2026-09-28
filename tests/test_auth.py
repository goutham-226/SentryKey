#tests/test_auth.py

# Test '/v1/auth/register' endpoint

"""
Test if /v1/auth/register returns 201
on succesfully creating a new user and 
returns the right output id,email,name 
and created_on.

Test if password and password_hash are never in the body.

Test if a duplicate Email raises 409.

Test if an invalid body returns 429.
"""
async def test_auth_returns_201_on_success_validate_output(client):
    request = {"email":"user@email.com","name":"user","password":"Mypassword@123"}
    
    response = await client.post('v1/auth/register',json=request)
    body = response.json()

    assert response.status_code == 201
    assert body['id'] == 1 # table truncates for every test function
    assert body['email'] == 'user@email.com'
    assert body['name'] == 'user'
    assert "created_on" in body
    
    assert not "password" in body
    assert not "password_hash" in body 

    # use the request  with the same email and check if it returns 409
    response = await client.post('v1/auth/register',json=request)
    assert response.status_code == 409
    
    #create an invalid request
    request = {"email":"new_user@email.com","name":"new_user"}
    response = await client.post('v1/auth/register',json=request)
    assert response.status_code == 422









