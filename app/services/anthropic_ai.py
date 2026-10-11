#services/anthropic_ai.py

#Send requests to the Anthropic AI API and handle responses.

#import anthropic to handle exceptions.
import anthropic
#import anthropic async client
from anthropic import AsyncAnthropic

# import app dependencies
from app.services.provider_data import provider_response
from app.config import get_settings
from app.schemas import ChatRequest

import logging

from fastapi import HTTPException, status


#get settings from config.py
settings = get_settings()

logger = logging.getLogger(__name__)

# create async anthropic client.
client = AsyncAnthropic(api_key=settings.anthropic_api_key)



async def get_anthropic_tokens(text: str, model: str,role: str) -> int:
    """
    Get the number of tokens in a text string for a given model.
    """
    # create request json for the anthropic client.
    message: dict[str,str] = {"role":role,"content":text}
    request: list[dict[str,str]] = [message]
    # use the anthropic client to get the number of tokens in the text.
    # model check happens in get_bearer_key dependency, so we can assume the model is valid.
    try:
        token_count: int = await client.messages.count_tokens(model=model, messages=request)
    except anthropic.APIError as e:
        logger.exception("count_tokens failed (%s) model=%s",type(e).__name__,model)
        raise HTTPException(
            status_code=500,
            detail="Provider isn't available at the moment.",
        ) 
    return token_count
