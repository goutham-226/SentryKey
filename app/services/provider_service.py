#services/provider_service.py
'''
A module with a method to get a chat request,
from POST /v1/chat/completions and return a
processed response.

TO-DO:
-----
-> make get_open_ai_prompt_tokens() async. ----> completed.
-> route a real request to open_ai and make sure your tests are passed. ------>

'''

#import anyio -> shield reservation release from cancellation
import anyio
from collections.abc import Sequence
#import fastapi HTTPException
from fastapi import HTTPException
# import sqlalchemy
from sqlalchemy import select, text, func, update, delete
#import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession
# import ChatRequest schema
from app.schemas import ChatRequest, ChatResponse
#import ApiKey model
from app.models import ApiKeys, UsageRecords, Models, Conversations, Messages
#import dataclass
from app.services.provider_data import provider_response
from app.services.open_ai import get_openai_tokens, get_openai_response


async def get_total_tokens(api_key: ApiKeys,prompt_tokens: int,payload: ChatRequest,db: AsyncSession) -> tuple[int, int, UsageRecords]:
    """
    A method to calculate
    total tokens used today.

    To prevent Race conditons -> lock ApiKeys row for reading, and reserve max_tokens in a UsageRecords row with status 'Reserved' and status_code 429.
    """
    _max_tokens = payload.max_tokens
    stmt = select(ApiKeys).where(ApiKeys.id == api_key.id).with_for_update() # lock the row for reading to prevent race conditions
    result = await db.execute(stmt)
    stmt = select(func.coalesce(func.sum(UsageRecords.prompt_tokens + UsageRecords.completion_tokens),0)).where(
                               UsageRecords.api_key_id == api_key.id,
                               UsageRecords.requested_at > func.now() - text("INTERVAL '1 day'"),
                             )
    result = await db.execute(stmt)
    total_tokens_used = result.scalar() # a single integer value of the total sum.
    total_tokens = total_tokens_used + prompt_tokens
    # if used tokens + prompt_tokens exceed quota limit raise HTTException.
    if total_tokens > api_key.daily_quota:
        raise HTTPException(
                             status_code = 429,
                             detail = 'Daily token limit exhausted.',
                            )
        # reassign max_tokens
    #vailable_tokens = daily_limit - total_tokens(tokens_used + prompt_tokens)
    available_tokens = api_key.daily_quota - total_tokens
        # max_tokens = min(available_tokens,max_tokens)
    _max_tokens =  min(available_tokens,_max_tokens)
        # if max_tokens is 0 raise 429
    if _max_tokens <= 0:
        raise HTTPException(
                status_code = 429,
                detail = 'Rate limit Exceeded.',
            )

    # reserve max_tokens to prevent race conditions where multiple requests are made at the same time and exceed the daily quota.
    reserve = UsageRecords(prompt_tokens=prompt_tokens,completion_tokens=_max_tokens,context_tokens=0,status='Reserved',status_code=429,api_key_id=api_key.id)
    db.add(reserve)
    await db.commit() # commit the reserved tokens to the database to prevent race conditions.
    return total_tokens_used, _max_tokens, reserve

 
async def get_model_provider(model: str,db: AsyncSession) -> str | None:
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
    flush (not commit) -> get_response commits it before the provider call,
    and release_reservation deletes it if the request fails.
    """
    conversation = Conversations(
                        api_key_id = api_key.id,
                        title = payload.prompt[:15],
                       )
    db.add(conversation)
    await db.flush() # assigns conversation.id
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
        await db.rollback() # end the read transaction -> runs before any tokens are reserved.
        raise HTTPException(
                   status_code = 404,
                   detail = 'Conversation does not exist.',
                  ) 

async def get_message_history(conversation_id: int, db: AsyncSession) -> Sequence[Messages]:
    """
    return a list of all messages,
    from old to new (created_on ascending) - trim_message_history picks the most recent ones that fit our context_budget.
    """
    stmt = select(Messages).where(Messages.conversation_id == conversation_id).order_by(Messages.created_on,Messages.id)
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return messages

async def trim_message_history(history: Sequence[Messages], api_key: ApiKeys, db: AsyncSession) -> tuple[list[dict[str,str]], int]:
    """
    Check daily context quota limit for api_key.
    Get Usage Records - context tokens used for the given day.
    reconstruct message history to fit token budget.
    return (trimmed messages, their total token count),
    ([], 0) if context cannot fit our quota budget.
    """
    stmt = select(ApiKeys.daily_context_quota).where(ApiKeys.id == api_key.id)
    result = await db.execute(stmt)
    daily_context_quota: int = result.scalar_one_or_none() or 0
   
    # get context tokens used for today
    stmt = select(func.coalesce(func.sum(UsageRecords.context_tokens),0)).where(
                                                            UsageRecords.api_key_id == api_key.id,
                                                            UsageRecords.requested_at > func.now() - text("INTERVAL '1 day'"),
                                                           )
    result = await db.execute(stmt)
    context_tokens_used: int = result.scalar()
  
    available_tokens = max(daily_context_quota - context_tokens_used, 0)
    if available_tokens == 0: 
        return [], 0

    # get last 8 messages (history is old to new, so these are the most recent)
    _trimmed_messages: Sequence[Messages] = history[-8:]

    kept_messages: list[Messages] = []

    total_tokens_requested: int = 0

    # walk newest to oldest so the most recent messages are kept first.
    for message in reversed(_trimmed_messages):
        # if the message doesnt fit the budget drop it and every older message.
        if total_tokens_requested + message.token_count > available_tokens:
            break
        total_tokens_requested += message.token_count
        kept_messages.append(message)

    # back to old to new for the provider.
    kept_messages.reverse()

    # context must start with a user message -> drop leading assistant messages
    # (odd slice parity or the budget cut off their user message).
    while kept_messages and kept_messages[0].role == 'assistant':
        total_tokens_requested -= kept_messages.pop(0).token_count

    trimmed_history: list[dict[str,str]] = [{'role': message.role, 'content': message.content} for message in kept_messages]
    return trimmed_history, total_tokens_requested


async def update_usage_history(payload: ChatRequest, api_key: ApiKeys, model_response: provider_response,row: UsageRecords,db: AsyncSession):
    """
    Settle the reservation row
    with the real token usage, and insert messages
    after getting a model response.
    """
    # UsageRecords.model_id references models.id, payload.model is the model slug.
    stmt = select(Models.id).where(Models.model_id == payload.model)
    result = await db.execute(stmt)
    model_id: int | None = result.scalar_one_or_none()

    # if model generated tokens insert messages.
    # if model failed before generation do not update messages -> doing so will affect history context trimmming and model performance.
    if model_response.started_generation:
        # insert user message
        user_message = Messages(
                             conversation_id = payload.conversation_id,
                             role = 'user',
                             model = payload.model,
                             content = payload.prompt,
                             token_count = model_response.prompt_tokens,
                            )
             
        db.add(user_message)
        await db.flush() 
        # insert assistant message
        assistant_message = Messages(
                                  conversation_id = payload.conversation_id,
                                  role = 'assistant',
                                  model = payload.model,
                                  content = model_response.response,
                                  token_count = model_response.completion_tokens,
                                 )

        db.add(assistant_message)
        await db.flush()

    # settle the reservation with the real usage -> the session sends an UPDATE on commit (expire_on_commit=False keeps row attached).
    # non-billable -> set prompt_tokens, completion_tokens and context_tokens to 0.
    # billable -> use the response values, interrupted generations add a 15 token buffer to completion_tokens.
    billable = model_response.billable
    row.model_id = model_id
    row.conversation_id = payload.conversation_id
    row.prompt_tokens = model_response.prompt_tokens if billable else 0
    row.completion_tokens = model_response.completion_tokens + model_response.token_buffer if billable else 0
    row.context_tokens = model_response.context_tokens if billable else 0
    row.status = model_response.status
    row.status_code = model_response.status_code
    # single commit -> messages and settled usage are written together.
    await db.commit()


async def release_reservation(reservation_id: int, db: AsyncSession, conversation_id: int | None = None):
    """
    Settle a reservation row to 0 tokens when the request
    fails before update_usage_history settles it -> otherwise the
    reserved prompt + max_tokens count against the daily quota for 24 hours.
    conversation_id -> a conversation created by this request, deleted so failed requests leave no empty conversations.
    """
    # roll back first -> the session may be in a failed state after the exception.
    await db.rollback()
    if conversation_id is not None:
        # safe to delete -> messages and the usage row only reference it once update_usage_history commits.
        await db.execute(delete(Conversations).where(Conversations.id == conversation_id))
    stmt = update(UsageRecords).where(UsageRecords.id == reservation_id).values(
                                     prompt_tokens = 0,
                                     completion_tokens = 0,
                                     context_tokens = 0,
                                     status = 'Failed',
                                     status_code = 500,
                                    )
    await db.execute(stmt)
    await db.commit()


async def get_response(payload: ChatRequest, api_key: ApiKeys, db: AsyncSession) -> ChatResponse:
    """
    get_response method takes 
    in payload and api_key,
    and routes it to a provider - current service inly provides 9 models from 3 providers
    openai,
    anthropic,
    google.
    returns a response.

    Handles rate-limiting, and context building.
    """

    _prompt: str = payload.prompt
    _model: str = payload.model
    # get daily token limit
    daily_token_limit: int = api_key.daily_quota

    # get provider for the payload model.
    _provider = await get_model_provider(model=_model,db=db)
    # get_input_tokens from a model provider.
    if _provider == 'openai':
        # get prompt tokens from provider function. 
        prompt_tokens = await get_openai_tokens(text=_prompt)

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

    # if conversation_id doesnt match users api_key raise an error.
    # checked before reserving tokens -> a 404 here never leaves a reservation behind.
    new_conversation = payload.conversation_id is None or payload.conversation_id == 0
    if not new_conversation:
        await raise_404_on_conversation_id_with_wrong_api_key(api_key=api_key,conversation_id=payload.conversation_id,db=db)

    total_tokens_used, _max_tokens, reservations = await get_total_tokens(api_key=api_key,prompt_tokens=prompt_tokens,payload=payload,db=db)
    # read the id now -> release_reservation rolls back, which expires the row object.
    reservation_id: int = reservations.id

    # change payloads max_tokens value
    payload.max_tokens = _max_tokens

    # id of a conversation created by this request -> deleted on failure.
    created_conversation_id: int | None = None

    # any failure from here until the reservation is settled must release it.
    try:
        # create conversation history
        # if no conversation_id was passed in create a new id
        if new_conversation:
            conversation = await create_conversation_id(payload=payload,api_key=api_key,db=db)
            payload.conversation_id = conversation.id
            created_conversation_id = conversation.id

        # get message histroy and handle context token budgeting.
        # short-term memory previous 8 messages (4-user + 4-assistant messages)
        message_history: Sequence[Messages]  = await get_message_history(conversation_id=payload.conversation_id,db=db)

        # trim messages so context tokens do'nt exceed daily limit.
        conversation_context, context_tokens = await trim_message_history(history=message_history,api_key=api_key,db=db)

        # end the transaction before the provider call -> returns the connection to the pool
        # instead of holding it idle while the model responds. also commits a new conversation.
        # update_usage_history checks out a connection again to settle the reservation.
        await db.commit()


        # send request to a provider.
        # unsupported providers already raised 404 before reserving tokens -> only wired providers reach here.
        # add an elif per provider as anthropic / google get wired.
        if _provider == 'openai':
            model_response = await get_openai_response(payload=payload,context=conversation_context,history_tokens=context_tokens)


        # update database
        await update_usage_history(payload=payload,api_key=api_key,model_response=model_response,row=reservations,db=db)

    # BaseException -> also catches asyncio.CancelledError (request cancelled while awaiting the provider).
    except BaseException:
        # shield -> a cancelled task would otherwise cancel the release's own awaits too.
        with anyio.CancelScope(shield=True):
            await release_reservation(reservation_id=reservation_id,db=db,conversation_id=created_conversation_id)
        raise

    # tokens used before this request + what the settled row actually billed.
    # (actual prompt can differ from the estimate, and non-billable rows settle to 0)
    tokens_used_after_response = total_tokens_used + reservations.prompt_tokens + reservations.completion_tokens
    # return chat response
    return ChatResponse(
                 model=payload.model,
                 output=model_response.response,
                 prompt_tokens=model_response.prompt_tokens,
                 completion_tokens = model_response.completion_tokens,
                 quota_remaining = max(daily_token_limit - tokens_used_after_response, 0),
                 conversation_id = payload.conversation_id,
                 error_detail = None,
                )
