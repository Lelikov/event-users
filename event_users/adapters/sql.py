from typing import TYPE_CHECKING

from sqlalchemy import text


if TYPE_CHECKING:
    from sqlalchemy.engine import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlExecutor:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch_one(self, query: str, values: dict) -> RowMapping | None:
        result = await self.session.execute(text(query), values)
        return result.mappings().first()

    async def fetch_all(self, query: str, values: dict) -> list[RowMapping]:
        result = await self.session.execute(text(query), values)
        return list(result.mappings().all())

    async def execute(self, query: str, values: dict) -> None:
        await self.session.execute(text(query), values)
        await self.session.commit()

    async def execute_in_transaction(self, statements: list[tuple[str, dict]]) -> None:
        if self.session.in_transaction():
            for query, values in statements:
                await self.session.execute(text(query), values)
            return

        async with self.session.begin():
            for query, values in statements:
                await self.session.execute(text(query), values)
