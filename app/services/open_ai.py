#services/open_ai.py
"""
Send requests to OpenAI SDK,
Handle exceptions and Network timeouts.
"""

#open-ai encoder returns a list of token_ids
import tiktoken


"""
Method to return open_ai token estimate
for a given prompt.
"""
def get_openai_prompt_tokens(prompt: str) -> int:
    encoding = tiktoken.get_encoding('o200k_base')     
    prompt_token_ids = encoding.encode(prompt)
    prompt_tokens = len(prompt_token_ids)
    return prompt_tokens


