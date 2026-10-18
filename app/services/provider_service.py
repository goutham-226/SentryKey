#services/provider_service.py
'''
A module with a method to get a chat request,
from POST /v1/chat/completions and return a
processed response.
'''

#import anyio -> shield reservation release from cancellation
import anyio
import logging
from collections.abc import Callable, Sequence
from datetime import timedelta
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
from app.services.anthropic_ai import get_anthropic_tokens, get_anthropic_response
from app.services.google_ai import get_gemini_tokens, get_gemini_response, get_replicate_response


logger = logging.getLogger(__name__)

# returned in error_detail when the reply hit max_tokens before finishing.
# max_tokens may already be lowered to the model's output limit or the remaining quota -> raising it only helps below those.
TRUNCATED_DETAIL = "Reply hit max_tokens before finishing (thinking tokens count toward it). Increase max_tokens for a complete answer, up to the model's output limit and your remaining quota."

async def get_total_tokens(api_key: ApiKeys,prompt_tokens: int,payload: ChatRequest,context_tokens: int,db: AsyncSession) -> tuple[int, int, UsageRecords]:
    """
    A method to calculate
    total tokens used today.

    To prevent Race conditons -> caller must hold the ApiKeys row lock (taken in trim_message_history),
    nothing may commit between that lock and this function's commit.
    reserve max_tokens in a UsageRecords row with status 'Reserved' and status_code 429.
    """
    _max_tokens = payload.max_tokens
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
    reserve = UsageRecords(prompt_tokens=prompt_tokens,completion_tokens=_max_tokens,context_tokens=context_tokens,status='Reserved',status_code=429,api_key_id=api_key.id)
    db.add(reserve)
    await db.commit() # commit the reserved tokens to the database to prevent race conditions.
    return total_tokens_used, _max_tokens, reserve

 
async def get_model_provider(model: str,db: AsyncSession) -> tuple[str | None, int | None]:
    """
    A method to get a model's provider and output cap (max_output_tokens).
    returns (None, None) for an unknown model.
    """
    stmt = select(Models.provider, Models.max_output_tokens).where(Models.model_id == model)
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None, None
    return row.provider, row.max_output_tokens


async def create_conversation_id(payload: ChatRequest, api_key: ApiKeys,db: AsyncSession) -> Conversations:
    """
    Create a new conversation and return.
    flush (not commit) -> get_total_tokens commits this with the reservation,
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
    stmt = select(ApiKeys.daily_context_quota).where(ApiKeys.id == api_key.id).with_for_update() # lock the row for reading to prevent race conditions
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

    trimmed_history: list[dict[str,str]] = []
    for message in kept_messages:
        if message.content != '':
            trimmed_history.append({'role':message.role,'content':message.content})

    return trimmed_history, total_tokens_requested


async def update_usage_history(payload: ChatRequest, api_key: ApiKeys, model_response: provider_response,row: UsageRecords,db: AsyncSession, created_conversation_id: int | None = None):
    """
    Settle the reservation row
    with the real token usage, and insert messages
    after getting a model response.
    created_conversation_id -> a conversation created by this request, deleted if no messages were saved
    (the model failed before generating, or produced no visible answer), so a failed first turn
    leaves no empty conversation. payload.conversation_id is set to None to tell the caller.
    """
    # UsageRecords.model_id references models.id, payload.model is the model slug.
    stmt = select(Models.id).where(Models.model_id == payload.model)
    result = await db.execute(stmt)
    model_id: int | None = result.scalar_one_or_none()

    # if model generated a visible answer insert messages.
    # if model failed before generation do not update messages -> doing so will affect history context trimmming and model performance.
    # an empty answer (e.g. thinking used all of max_tokens) is not saved either -> it would leave an unanswered user turn in the history.
    if model_response.started_generation and model_response.response.strip():
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
                                  # visible tokens only -> reasoning tokens are never resent as context.
                                  token_count = model_response.response_tokens,
                                 )

        db.add(assistant_message)
        await db.flush()

    # nothing saved on a conversation this request created -> it would stay empty, delete it.
    # an existing conversation is kept -> it still holds earlier turns.
    elif created_conversation_id is not None:
        await db.execute(delete(Conversations).where(Conversations.id == created_conversation_id))
        payload.conversation_id = None

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
    # single commit -> messages (or the conversation delete) and settled usage are written together.
    await db.commit()


async def release_reservation(reservation_id: int, db: AsyncSession, conversation_id: int | None = None):
    """
    Settle a reservation row to 0 tokens when the request
    fails before update_usage_history settles it -> otherwise the
    reserved prompt + max_tokens count against the daily quota for 24 hours.
    conversation_id -> a conversation created by this request, deleted so failed requests leave no empty conversations.
    only touches a row still 'Reserved' -> a reservation already settled by update_usage_history
    (e.g. cancelled right after its commit) is left alone, along with its conversation and messages.
    """
    # roll back first -> the session may be in a failed state after the exception.
    await db.rollback()
    stmt = update(UsageRecords).where(UsageRecords.id == reservation_id, UsageRecords.status == 'Reserved').values(
                                     prompt_tokens = 0,
                                     completion_tokens = 0,
                                     context_tokens = 0,
                                     status = 'Failed',
                                     status_code = 500,
                                    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        await db.rollback() # the row was already settled by update_usage_history -> rollback to end the transaction.
        return
    if conversation_id is not None:
        # the conversation was created by this request -> delete it.
        await db.execute(delete(Conversations).where(Conversations.id == conversation_id))
    await db.commit()


async def release_stale_reservations(older_than: timedelta, db: AsyncSession) -> int:
    """
    Settle reservation rows to 0 tokens when they are still 'Reserved' after older_than.
    A worker that dies between reserving and settling (SIGKILL, out of memory, host failure)
    never runs release_reservation -> without this the reserved prompt + max_tokens
    count against the daily quota for 24 hours.
    status 'Expired' -> tells a swept row apart from a request that failed and released itself.
    safe to run from every worker at once -> only rows still 'Reserved' are touched.
    a live request whose row is swept still settles it -> update_usage_history overwrites the row by id.
    returns the number of rows released.
    """
    stmt = update(UsageRecords).where(
                               UsageRecords.status == 'Reserved',
                               UsageRecords.requested_at < func.now() - older_than,
                              ).values(
                                     prompt_tokens = 0,
                                     completion_tokens = 0,
                                     context_tokens = 0,
                                     status = 'Expired',
                                     status_code = 500,
                                    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount


async def sweep_stale_reservations(interval_seconds: float, older_than: timedelta, session_factory: Callable[[], AsyncSession]):
    """
    Run release_stale_reservations every interval_seconds, forever.
    started by the app's lifespan -> sweeps once at startup, so a restart after a crash frees quota straight away.
    a failed sweep is logged and retried on the next pass -> it never stops the loop.
    """
    while True:
        try:
            async with session_factory() as db:
                released = await release_stale_reservations(older_than=older_than,db=db)
            if released:
                logger.warning('Released %s stale reservation(s) older than %s', released, older_than)
        except Exception:
            logger.exception('Failed to release stale reservations')
        await anyio.sleep(interval_seconds)


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

    # get provider and output cap for the payload model.
    _provider, max_output_tokens = await get_model_provider(model=_model,db=db)
    # cap max_tokens to the model's output limit before reserving -> the provider would reject a larger value with a 400,
    # and reserving tokens the model can never generate would hold back parallel requests for nothing.
    if max_output_tokens is not None:
        payload.max_tokens = min(payload.max_tokens, max_output_tokens)
    # get_input_tokens from a model provider.
    if _provider == 'openai':
        # get prompt tokens from provider function. 
        prompt_tokens = await get_openai_tokens(text=_prompt)

    elif _provider == 'anthropic':
        prompt_tokens = await get_anthropic_tokens(text=_prompt,model=_model,role='user')

    elif _provider == 'google':
        # model not available at the moment
        prompt_tokens = await get_gemini_tokens(text=_prompt,model=_model)

    else:
        raise HTTPException(
                     status_code = 404,
                     detail = 'Model not provided by our service.',
                    )

    # if conversation_id doesnt match users api_key raise an error.
    # checked before reserving tokens -> a 404 here never leaves a reservation behind.

    created_conversation_id: int | None = None

    new_conversation: bool = payload.conversation_id is None or payload.conversation_id == 0
    if not new_conversation: # conversation_id is provided -> check if it belongs to the api_key.
        await raise_404_on_conversation_id_with_wrong_api_key(api_key=api_key,conversation_id=payload.conversation_id,db=db)
      
    else:
        conversation = await create_conversation_id(payload=payload,api_key=api_key,db=db)
        payload.conversation_id = conversation.id
        created_conversation_id = conversation.id
    
    # get message histroy and handle context token budgeting.
    # short-term memory previous 8 messages (4-user + 4-assistant messages)
    message_history: Sequence[Messages]  = await get_message_history(conversation_id=payload.conversation_id,db=db)
    
    # trim messages so context tokens do'nt exceed daily limit.
    conversation_context, context_tokens = await trim_message_history(history=message_history,api_key=api_key,db=db)
    

    

    total_tokens_used, _max_tokens, reservations = await get_total_tokens(api_key=api_key,prompt_tokens=prompt_tokens,payload=payload,context_tokens=context_tokens,db=db)
    # read the id now -> release_reservation rolls back, which expires the row object.
    reservation_id: int = reservations.id

    # change payloads max_tokens value
    payload.max_tokens = _max_tokens

   

    # any failure from here until the reservation is settled must release it.
    try:
        # send request to a provider.
        # unsupported providers already raised 404 before reserving tokens -> only wired providers reach here.
        # add an elif per provider as anthropic / google get wired.
        if _provider == 'openai':
            model_response: provider_response = await get_openai_response(payload=payload,context=conversation_context,history_tokens=context_tokens,prompt_tokens=prompt_tokens)

        elif _provider == 'anthropic':
            model_response: provider_response = await get_anthropic_response(payload=payload,context=conversation_context,history_tokens=context_tokens,prompt_tokens=prompt_tokens)

        elif _provider == 'google' and _model != 'google/gemini-3.1-pro':
            model_response: provider_response = await get_gemini_response(payload=payload,context=conversation_context,history_tokens=context_tokens,prompt_tokens=prompt_tokens)

        elif _provider == 'google' and _model == 'google/gemini-3.1-pro':
            model_response: provider_response = await get_replicate_response(payload=payload,context=conversation_context,history_tokens=context_tokens,prompt_tokens=prompt_tokens)
        # update database
        await update_usage_history(payload=payload,api_key=api_key,model_response=model_response,row=reservations,db=db,created_conversation_id=created_conversation_id)

    # BaseException -> also catches asyncio.CancelledError (request cancelled while awaiting the provider).
    except BaseException:
        # shield -> a cancelled task would otherwise cancel the release's own awaits too.
        with anyio.CancelScope(shield=True):
            try:
                await release_reservation(reservation_id=reservation_id,db=db,conversation_id=created_conversation_id)
            except Exception:
                logger.exception('Failed to release reservation %s', reservation_id)
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
                 error_detail = TRUNCATED_DETAIL if model_response.status == 'Truncated' else None,
                )
