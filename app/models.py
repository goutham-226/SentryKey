'''
* convert our existing SQL into object relational mapping using sqlalchemy
*
'''
from datetime import datetime
from sqlalchemy import *
from sqlalchemy.orm import *
      
class Base(DeclerativeBase): # one instance to hold all the metadata for accurate schema
    pass

class Users(Base):
    __tablename__ = Users
    id: Mapped[int] = mapped_column(BIGSERIAL,pre

