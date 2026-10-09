#tests/test_subscribe.py

# Test the endpoint POST /v1/subscriptions.



"""
Test if subscribing to a valid tier
returns 201, with tier_name and period end.
"""
async def test_subscriptions_returns_201_and_tier_name_with_period_end(client,user):
     request = {'tier':'Pro'}
     email = user['email']
     password = user['password']
     response =  await client.post('/v1/subscriptions',json=request,auth=(email,password))
     body = response.json()

     assert response.status_code == 201
     assert body['tier'] ==  'Pro'
     assert 'period_end' in body
     
"""
Test if Subscribing again 
after a subscription exists returns 409.
"""
async def test_subscription_returns_409_when_a_subscriptiuon_exists(client,user):
    email = user['email']
    password = user['password']
   
    #create a subscription
    request = {'tier':'Pro'}
    response = await client.post('/v1/subscriptions',json=request,auth=(email,password))
    
    #create a new subscription for the same user.
    response = await client.post('/v1/subscriptions',json=request,auth=(email,password))
    
    assert response.status_code == 409
	

"""
Test if bad credentials return 401.

no user required test with random creds.
"""
async def test_subscription_returns_401_with_bad_credentials(client):
    email = 'user@example.com'
    password = 'password@12345'

    request = {'tier':'Basic'}
    response = await client.post('/v1/subscriptions',json=request,auth=(email,password))
    
    assert response.status_code == 401 






























    









