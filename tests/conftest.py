"""Shared fakes for event-users tests.

The service talks to PostgreSQL through the ISqlExecutor protocol only,
so adapters are tested against a recording fake (same convention as the
sibling services' suites).
"""

import os


os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("API_BEARER_TOKEN", "test-static-token")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("CRM_API_URL", "https://crm.test")
os.environ.setdefault("CRM_API_TOKEN", "test-crm-token")
os.environ.setdefault("CRM_ENCRYPTION_KEY", "00" * 32)

from typing import Self

import pytest


class FakeSqlExecutor:
    """Records every statement; responses are programmed per-call via queues."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, dict]] = []
        self.fetch_one_results: list = []
        self.fetch_all_results: list = []

    async def fetch_one(self, query: str, values: dict):
        self.statements.append((query, values))
        if self.fetch_one_results:
            return self.fetch_one_results.pop(0)
        return None

    async def fetch_all(self, query: str, values: dict) -> list:
        self.statements.append((query, values))
        if self.fetch_all_results:
            return self.fetch_all_results.pop(0)
        return []

    async def execute(self, query: str, values: dict) -> None:
        self.statements.append((query, values))


class FakeSession:
    """Minimal AsyncSession stand-in for code that manages commit/rollback itself."""

    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True


class FakeSessionmaker:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        session = FakeSession()
        self.sessions.append(session)
        return session


@pytest.fixture
def sql() -> FakeSqlExecutor:
    return FakeSqlExecutor()
