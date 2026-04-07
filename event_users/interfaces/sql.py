from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from sqlalchemy.engine import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession


class ISqlExecutor(Protocol):
    async def fetch_one(self, query: str, values: dict) -> RowMapping | None: ...

    async def fetch_all(self, query: str, values: dict) -> list[RowMapping]: ...

    async def execute(self, query: str, values: dict) -> None: ...

    async def execute_in_transaction(self, statements: list[tuple[str, dict]]) -> None: ...


class ISqlExecutorFactory(Protocol):
    def __call__(self, session: AsyncSession) -> ISqlExecutor: ...
