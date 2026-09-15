import asyncio
import replicate
from replicate.client import Client
from app.config import Settings,get_settings

input = {
    "prompt": "expalin Breadth First search on Binary Trees in C , Java and python3",
    "max_tokens":1000,
}

settings = get_settings()

client = Client(api_token=settings.replicate_api_token)

async def model_call():
    prediction = await client.predictions.async_create(
        model='qwen/qwen3-235b-a22b-instruct-2507',
        input=input,
    )
    await prediction.async_wait()
    print(dict(prediction))

asyncio.run(model_call())