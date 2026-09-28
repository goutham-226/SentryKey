#tests/test_schemas.py

# test pydantic BaseModels

import pytest
from pydantic import ValidationError
from app.schemas import UserCreate, SubscribeCatalog, ChatRequest

"""
Test if UserCreate accepts an 8-characters long password,
and a valid email.
"""
def test_usercreate_accepts_8_letter_pass_and_valid_email():
    password = 'MyPasswo'
    email = 'user@email.com'
    name = 'user'
    user = UserCreate(
               email=email,
               name=name,
               password=password,
           )
    assert user.password == password
    assert user.email == email 
    assert user.name == name


"""
Test if Pydantic Raises Validation Error
from 7 letter long password and wrong email format.
"""
def test_usercreate_raises_validation_error():
    password = '1234567'
    email = 'user@email.com'
    name = 'user'
    # test if it raises an error for short password
    with pytest.raises(ValidationError):
        user = UserCreate(
                   email=email,
                   name=name,
                   password=password,
                )
    # test if it raises an error for a wrong email
    with pytest.raises(ValidationError):
        user = UserCreate(
                   email='user123',
                   name=name,
                   password='12345678',
               )
        
 
"""
Test if UserCreate accepts 27 character long password,
and 100 letter long name.
"""
def test_usercreate_accepts_27_letter_lon_pass_and_100_letter_long_name():
    name = ''
    for i in range(100):
        name += 'a'
    password = '123456789012345678901234567'
    user = UserCreate(
               email='user@email.com',
               name=name,
               password=password,
           )
    assert user.name == name
    assert user.password == password
    assert user.email == 'user@email.com'

"""
Test if UserCreate raises ValidationError for passwords longer than 
27 characters and names longer than 100 characters.
"""
def test_usercreate_raises_validation_error_on_wrong_input_formatting():
    name = ''
    for i in range(100):
        name += 'a'
    # test with long password
    with pytest.raises(ValidationError):
        user = UserCreate(
                   email='user@email.com',
                   name=name,
                   password='1234567890123456789012345678'
               )
    name = ''
    for i in range(101):
        name += 'a'
    # test with a long name
    with pytest.raises(ValidationError):
        user = UserCreate(
                   email='user@email.com',
                   name=name,
                   password='123456789012345678901234567'
               )
         
"""
Test if SubscribeCatalog raises ValidationError,
for any tier other than basic,pro, and premium.
"""
def test_SubscribeCatalog_raises_error_for_invalid_tier():
    # test if it accepts basic pro and premium
    sb1 = SubscribeCatalog(
              tier='Basic',
           )
    sb2 = SubscribeCatalog(
              tier='Pro',
          )
    sb3 = SubscribeCatalog(
              tier='Premium',
          )
    assert sb1.tier == 'Basic'
    assert sb2.tier == 'Pro'
    assert sb3.tier == 'Premium'
    # test if it raises ValidationError for wrong input 
    with pytest.raises(ValidationError):
        user = SubscribeCatalog(
                   tier='Wrong_tier',
               )
   
"""
Check how chat request behaves when conversation_id is not passed
should be None.
"""
def test_chat_request_without_conversation_id():
    chat = ChatRequest(
              prompt='prompt',
              model='gpt-5.6-luna',
              max_tokens=100,
           )
    assert chat.conversation_id is None



































