#services/provider_response.py
'''
A module with a method to get a chat request,
from POST /v1/chat/completions and return a
processed response.

TO-DO:
-----
-> make get_open_ai_prompt_tokens() async. ----> completed.
-> route a real request to open_ai and make sure your tests are passed. ------>

'''

#import fastapi HTTPException
from fastapi import HTTPException
# import sqlalchemy
from sqlalchemy import select, text, func
#import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession
# import ChatRequest schema
from app.schemas import ChatRequest, ChatResponse
#import ApiKey model
from app.models import ApiKeys, UsageRecords, Models, Conversations, Messages, Users
#import dataclass
from app.services.provider_data import provider_response
from app.services.open_ai import get_openai_prompt_tokens


async def get_total_tokens(api_key: ApiKeys, db: AsyncSession) -> int:
    """
    A method to calculate
    total tokens used today.
    """
    stmt = select(func.coalesce(func.sum(UsageRecords.prompt_tokens + UsageRecords.completion_tokens),0)).where(
                               UsageRecords.api_key_id == api_key.id,
                               UsageRecords.requested_at + text("INTERVAL '1 day'") > func.now(),
                             )
    result = await db.execute(stmt)
    total_tokens = result.scalar() # a single integer value of the total sum.
    
    return total_tokens

 
async def get_model_provider(model: str,db: AsyncSession) -> str:
    """
    A method to get a model's provider.
    """
    stmt = select(Models.provider).where(Models.model_id == model)
    result = await db.execute(stmt)
    provider = result.scalar_one_or_none()

    return provider 


async def create_conversation_id(payload: ChatRequest, api_key: ApiKeys,db: AsyncSession) -> Conversations:
    """
    Create a new conversation and return.
    """
    conversation = Conversations(
                        api_key_id = api_key.id,
                        title = payload.prompt[:15],
                       )
    db.add(conversation)
    await db.commit()
    return conversation

async def raise_404_on_conversation_id_with_wrong_api_key(api_key: ApiKeys, conversation_id: int, db: AsyncSession):
    """
    raise 404 on conversation_id that doesnt belong to an api_key
    """
    stmt = select(Conversations).where(
                          Conversations.api_key_id == api_key.id,
                          Conversations.id == conversation_id,
                         )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
                   status_code = 404,
                   detail = 'Conversation does not exist.',
                  ) 

async def get_message_history(conversation_id: int, db: AsyncSesssion) -> list[Messages]:
    """
    return a list of all messages,
    from new to old - to be able to trim the most recent tokens that fit our context_budget.
    """
    stmt = select(Messages).where(Messages.conversation_id == conversation_id).order_by(Messages.created_on)
    result = db.execute(stmt)
    messages = result.scalar.all()
    if messages is None:
        return []
    return messages

async def trim_message_history(histrory: list[Messages], api_key: ApiKeys, db: AsyncSession) -> list[dict[str,str]]:
    """
    Check daily context quota limit for api_key.
    Get Usage Records - context tokens used for the given day.
    reconstruct message history to fit token budget.
    return empty list if context cannot fit our quota budget.
    """
    stmt = select(ApiKeys.daily_context_quota).where(ApiKeys.id == api_key.id)
    result = await db.execute(stmt)
    daily_context_quota: int = result.scalar_one_or_none()
   
    # get context tokens used for today
    stmt = select(func.coalesce(func.sum(UsageRecords.context_tokens))).where(
                                                            UsageRecords.api_key_id == api_key.id,
                                                            UsageRecords.requested_at + text("INTERVAL '1 day'") > func.now(),
                                                           )
    result = await db.execute(stmt)
    context_tokens_used: int = result.scalar_one_or_none()
  
    # get last 4 conversations
    _count: int = 0
    _trimmed_messages: list[Messages] = []
    history.reverse() # first messages in the  list  are the latest
   
    for messages in history:
        if _count == 8:
            break
        _trimmed_messages.append(messages)
        _count += 1
    
    available_tokens = daily_context_quota + context_tokens_used 
    if available_tokens == 0: 
        return []
    
    trimmed_history: list[dict[str,str]] = []
    my_dict: dict[str,str] = {}

    total_tokens_requested: int = 0    

    for message in _trimmed_messages:
        token_count = message.token_count
        total_tokens_requested += token_count
        content = message.content
        # if total_tokens are > than available trim the last message so it fits the budget.
        if total_tokens_requested > available_tokens:
            keep = token_count - (total_tokens_requested - available_tokens)
            if keep == 0:
                break
            content = message.content[:keep]
            
        my_dict = {'role': message.role, 'content':content}
        trimmed_history.append(my_role)            
      
    return trimmed_history


async def update_usage_history(payload: ChatRequest, api_key: ApiKeys, model_resposne: provider_response,db: AsyncSession):
    """
    Update usage records
    with new token usage and messages
    after getting a model response.
    """
    # if model failed due to a non-billable exception.
    if not model_response.started_generation and not model_response.billable:
        # do not update conversations or messages -> doing so will affect history context trimmming and model performance.
        # request is not billable so set prompt_tokens, completion_tokens and context_tokens to 0.
        usage = UsageRecords(
                           api_key_id = api_key.id,
                           prompt_tokens = 0,
                           completion_tokens = 0,
                           context_tokens = 0,
                           status = model_response.status,
                           status_code = model_response.status_code,
                         )
        db.add(usage)
        await db.commit()
    
    # if model failed with a billable exception.
    elif not model_response.started_generation and model_response.billable:
         # do not update conversations and messages.
         # update usagerecords -> a buffer of 15 tokens is added to a billable exception.
         usage = UsageRecords(
                           api_key_id = api_key.id,
                           prompt_tokens = model_response.prompt_tokens,
                           completion_tokens = model_response.completion_tokens,
                           context_tokens = model_response.context_tokens,
                           status=model_response.status,
                           status_code = model_response.status_code,
                          )
         db.add(usage)
         await db.commit()   
    # billable and generated some tokens
    else:
        # insert Messages
        user_message = Messages(
                             conversation_id = payload.conversation_id,
                             role = 'user',
                             model = payload.model_id,
                             content = payload.prompt,
                             token_count = model_response.prompt_tokens,
                            )
             
        db.add(user_message)
        await db.flush()
            # insert assistant message
        assistant_message = Messages(
                                  conversation_id = payload.conversation_id,
                                  role = 'assistant',
                                  model = payload.model_id,
                                  content = model_response.response,
                                  token_count = model_response.completion_tokens,
                                 )

        db.add(assistant_message)
        await db.flush()
        # insert usage_records
        usage = UsageRecords(
                         api_key_id = api_key.id,
                         model_id = payload.model_id,
                         conversation_id = payload.conversation_id,
                         prompt_tokens = model_response.prompt_tokens,
                         completion_tokens = model_response.completion_tokens,
                         context_tokens = model_response.context_tokens,
                         status = model_response.status,
                         status_code = model_response.status_code,
                       )                        
        db.add(usage)
        await db.commit()
    return conversation


async def get_response(payload: ChatRequest, api_key: ApiKeys, db: AsyncSession) -> ChatResponse:
    """
    get_response method takes 
    in payload and api_key,
    and routes it to a provider - current service inly provides 9 models from 3 providers
    openai,
    anthropic,
    gemini.
    returns a response.

    Handles rate-limiting, and context building.
    """

    _prompt = payload.prompt
    _model = payload.model
    _max_tokens = payload.max_tokens
    _conversation_id = payload.conversation_id 
    # get daily token limit
    daily_token_limit = api_key.daily_quota

    # get provider for the payload model.
    _provider = await get_model_provider(model=_model,db=db)
    # get_input_tokens from a model provider.
    if _provider == 'openai':
        # get prompt tokens from provider function. 
        prompt_tokens = await get_openai_prompt_tokens(prompt=_prompt)

    elif _provider == 'anthropic':
        # model not available at this moment
        raise HTTPException(
                      status_code = 404,
                      detail = 'Model not available at the moment.',
                     ) 

    elif _provider == 'google':
        # model not available at the moment
        raise HTTPException(
                       status_code = 404,
                       detail = 'Model not available at the moment.',
                     )

    else:
        raise HTTPException(
                     status_code = 404,
                     detail = 'Model not provided by our service.',
                    )

    
    total_tokens_used = await get_total_tokens(api_key=api_key,db=db) 
    # total_tokens = used_tokens + prompt_tokens
    total_tokens = total_tokens_used + prompt_tokens
    # if used tokens + prompt_tokens exceed quota limit raise HTTException.
    if total_tokens > daily_token_limit:
        raise HTTPException(
                         status_code = 429,
			 detail = 'Daily token limit exhausted.',
			)
    # reassign max_tokens
    # available_tokens = daily_limit - total_tokens(tokens_used + prompt_tokens)
    available_tokens = daily_token_limit - total_tokens
    # max_tokens = min(available_tokens,max_tokens)
    _max_tokens = min(available_tokens,_max_tokens)
    # if max_tokens is 0 raise 429
    if _max_tokens == 0:
        raise HTTPException(
            status_code = 429,
            detail = 'Rate limit Exceeded.',
          )
    # change payloads max_tokens value
    payload.max_tokens = _max_tokens
    
    # create conversation history
    # if no conversation_id was passed in create a new id
    if payload.conversation_id is None or payload.conversation_id == 0:
        conversation = await create_conversation_id(payload=payload,api_key=api_key,db=db)
   
    # if conversation_id doesnt match users api_key raise an error.
    else:
        await raise_404_on_conversation_id_with_wrong_api_key(api_key=api_key,conversation_id=payload.conversation_id,db=db)
    
    payload.conversation_id = conversation.id
   
    # get message histroy and handle context token budgeting.
    # short-term memory previous 4 conversation messages (4-user + 4-assistant messages) 
    message_history: list[Messages]  = await get_message_history(conversation_id=payload.conversation_id,db=db)
    
    # trim messages so context tokens do'nt exceed daily limit.
    conversation_context: list[dict[str,str]] = await trim_message_history(history=message_history,api_key=api_key,db=db)


    # send request to a provider.
    if _provider == 'openai':
        model_response = await get_openai_response(payload)        

    elif _provider == 'anthropic':
        # wire provider later
        raise HTTPException(
                status_code = 404,
                detail = 'Model not available at the moment.',
              )
    
    elif _provide == 'google':
        raise HTTPException(
              status_code = 404,
              detail = 'Model not available at the moment.',
             )

    else:
        raise HTTPException(
                   status_code = 404,
                   detail = 'Model is not provided by our service.',
                  )


   # update database
   await update_usage_history(payload=payload,api_key=api_key,model_response=model_response,db=db)
   #
   tokens_used_after_response = total_tokens_used + model_response.prompt_tokens + model_response.completion_tokens
   # return chat response
   return ChatResponse(
                model=payload.model_id,
                ouptut=model_response.response,
                prompt_tokens=model_response.prompt_tokens,
                completion_tokens = model_response.completion_tokens,
                conversation_id = conversation.id,
               )
 

