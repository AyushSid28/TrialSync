from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional

T = TypeVar("T")
ID = TypeVar("ID")


class Entity(ABC):
    pass


class Repository(ABC, Generic[T, ID]):
    @abstractmethod
    async def create(self, entity: T) -> T:
        pass

    @abstractmethod
    async def get_by_id(self, entity_id: ID) -> Optional[T]:
        pass

    @abstractmethod
    async def get_all(self, skip: int = 0, limit: int = 100) -> list[T]:
        pass

    @abstractmethod
    async def update(self, entity_id: ID, entity: T) -> Optional[T]:
        pass

    @abstractmethod
    async def delete(self, entity_id: ID) -> bool:
        pass
