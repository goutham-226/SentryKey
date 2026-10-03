#tests/test_chat_history.py
#Test GET /v1/chat-history/{conversation_id}

# import SessionLocal for db writes and reads
from app.db import SessionLocal
from app.models import Messages, Conversations

"""
Test if a user, gets all their messages with
correct roles and orders.

create a list of messages that you are manually adding to the conversation - Use Messages object.
use subscribed_api_key fixture.

use SessionLocal to create
messages with different roles - User, Assistant and a conversation id with the subscribed api_key.

call GET /v1/chat-history/{conversation_id} and get a list.

Iterate and assert with the initial created list.
"""
async def test_chat_history_returns_all_messages_with_the_right_format_and_order(client,subscribed_api_key):
    api_key = await subscribed_api_key(tier='Basic')   
   
    raw_key = api_key['api_key']
    key_id = api_key['key_id']

    # initialise an empty list to store all the messages that will be added to our conversation
    message_list = []
   
    # create empty conversation
    async with SessionLocal() as db:
        conversation = Conversations(api_key_id=key_id,title='New Conversation')
        db.add(conversation)
        await db.commit()

    # build messages
    user_message_1 = Messages(conversation_id = conversation.id,
			      role='user',
                              model='gpt-5.6-luna',
                              content='what was the first object-oriented-language',
                              token_count=7,
                             )
    #append message to the list 
    message_list.append(user_message_1)

    assistant_message_1 = Messages(conversation_id = conversation.id,
                                   role='assistant',
                                   model='gpt-5.6-luna',
                                   content='Simula is widely recognized as the first object-oriented-language',
                                   token_count=10,
                                  )
    # append messaged to the list
    message_list.append(assistant_message_1)

    user_message_2 = Messages(conversation_id = conversation.id,
                              role='user',
                              model='gpt-5.6-luna',
                              content='when was it invented?',
                              token_count=4,
                             )
   
    message_list.append(user_message_2)
    
    assistant_message_2 = Messages(conversation_id = conversation.id,
                                   role='assitant',
                                   model='gpt-5.6-luna',
                                   content='Simula was developed between 1961 and 1962.',
                                   token_count=7,
                                  )

    message_list.append(assistant_message_2)

    # add these message rows to the database chronologically
    async with SessionLocal() as db:
        for message in message_list:
            db.add(message)
            await db.flush()            
        
        await db.commit()
   
    header = {'Authorization': f'Bearer {raw_key}'}

    # call endpoint GET /v1/chat-history/{conversation-id}
    response = await client.get(f'/v1/chat-history/{conversation.id}',headers=header)

    assert response.status_code == 200

    messages = response.json()

    i = 0 # index for message_list
    # iterate and assert messages
    for message in messages:
        assert message['conversation_id'] == message_list[i].conversation_id
        assert message['role'] == message_list[i].role
        assert message['message'] == message_list[i].content
        assert message['model'] == message_list[i].model
        assert 'timestamp' in message
        i += 1

     


"""
Test if GET /v1/chat-history/{conversation_id} raises 404,
on a conversation_id that doesnt exist.
"""
async def test_if_chat_history_raises_404_on_a_conversation_id_that_does_not_exist(client,subscribed_api_key):
    api_key = await subscribed_api_key(tier='Basic')
   
    raw_key = api_key['api_key']
    key_id = api_key['key_id']

    # a fake conversation_id
    conversation_id = 3
   
    header = {'Authorization': f'Bearer {raw_key}'}
    # send a req to the endpoint
    response = await client.get(f'/v1/chat-history/{conversation_id}',headers=header)

    assert response.status_code == 404

"""
Test if GET /v1/chat-history/{conversation_id} raises 404,
when key A requests key B's conversation.

create two keys for the same user.

add two messages to a conversation for key A.

send a req to GET /v1/chat-history/{conversation_id} using Key B.

"""
async def test_if_chat_history_raises_404_on_a_different_key(client,subscribed_user):
    # create Key A and Key B
    user = await subscribed_user(tier='Basic')
    
    email = user['email']
    password = user['password']

    
    request = {'email':email,'password':password}
    
    # create key A
    response = await client.post('/v1/keys',json=request)
   
    assert response.status_code == 201  

    key_A = response.json()['api_key']
    key_A_id = response.json()['key_id']

    # create key B
    response = await client.post('v1/keys',json=request)

    assert response.status_code == 201
   
    key_B = response.json()['api_key']
    key_B_id = response.json()['key_id']

    # create conversations for key A
    async with SessionLocal() as db:
        conversation = Conversations(api_key_id=key_A_id,title='New Conversation.')
        db.add(conversation)
        await db.flush()
        
        message = Messages(conversation_id = conversation.id,
                           role = 'user',
                           model = 'gpt-5.6-luna',
                           content = 'Name a radioactive element ?',
                           token_count = 5,
                          )

        db.add(message)
        await db.flush()

        message = Messages(conversation_id = conversation.id,
                           role = 'user',
                           model = 'gpt-5.6-luna',
                           content = 'Uranium is a radioactive element that is found naturally on Earth.',
                           token_count = 11,
                          )
        db.add(message)
        await db.commit()

    # request conversation-history with conversation.id and key B
    header = {'Authorization': f'Bearer {key_B}'}
   
    response = await client.get(f'/v1/chat-history/{conversation.id}',headers=header)
    
    assert response.status_code == 404 






 



































