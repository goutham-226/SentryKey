# tests/test_security.py

# Check if passwords are hashed and verified properly.

from app.security import hash_password, verify_password


"""
Test wether a hashed password is verified.
"""
def test_password_hash_and_verify_return_true():
    password = 'Mypassword@12345'
 
    # hash it using our hashing method
    hashed = hash_password(password)
    
    # check if verify_password returns true for the same_password
    verify  = verify_password(password,hashed)

    assert verify == True
"""
Test wether verify_password returns false for wrong passwords.
"""
def test_wrong_password_ret_false():
    password = 'MyPassword@12345'
    wrong_password = 'LazyHorse@69'
    
    hashed = hash_password(password)

    verify = verify_password(wrong_password,hashed)

    assert verify == False 

"""
Test wether two Hashes of the same password text are different.
"""
def test_different_hash_for_the_same_password():
    password = 'Mypassword@123'
    
    hashed_1 = hash_password(password)
    hashed_2 = hash_password(password)
    
    assert hashed_1 != hashed_2 















