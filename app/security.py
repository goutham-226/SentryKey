from passlib.context import CryptContext

pwd = CryptContext(scheme=["bcrypt"],deprecate="auto")


def hash_password(password: str) -> str:
    password = pwd.hash(password)
    return password

def verify_password(password: str, hashed_password: str) -> bool:
    return pwd.verify(password,hashed_password) 
