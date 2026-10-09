# tests/test_health.py

# -- no imports needed can use client from conftest
# pytest auto includes fixtures from conftest into your tests

async def test_health_returns_ok(client):
    # health has no dependencies
    response = await client.get('/health')
    
    #check if method returned status code 200
    assert response.status_code == 200
    # check if it returned {"status":"ok"}
    assert response.json()["status"] == "ok"

   
