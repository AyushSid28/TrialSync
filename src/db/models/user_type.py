from enum import Enum

from sqlalchemy import Enum as SQLAlchemyEnum, String


class UserType(Enum):
    PATIENT = "patient"
    USER = "user"


SQLAlchemyEnum(UserType, name="user_type")
