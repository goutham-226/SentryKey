#services/open_ai.py
"""
Send requests to OpenAI SDK,
Handle exceptions and Network timeouts.
"""
#import openai to handle exceptions
import openai
# import openai async client
from openai import AsyncOpenAI

# import sql alchemy AsyncSe



#open-ai encoder returns a list of token_ids
import tiktoken
# import asyncio to offload encoding onto a thread.
import asyncio


encoding = tiktoken.get_encoding('o200k_base')


async def get_openai_prompt_tokens(prompt: str) -> int:
    """
    Return OpenAI token estimate
    using tiktoken.
    """
    prompt_token_ids = await asyncio.to_thread(encoding.encode, prompt)
    prompt_tokens = len(prompt_token_ids)
    return prompt_tokens


