"""Shared SQLAlchemy declarative base for all ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single metadata registry for Alembic and create_all."""

    pass
