"""Shared fakes for event-users tests.

The service talks to PostgreSQL through the ISqlExecutor protocol only,
so adapters are tested against a recording fake (same convention as the
sibling services' suites).
"""

import os


os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("API_BEARER_TOKEN", "test-static-token")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("CRM_API_URL", "https://crm.test")
os.environ.setdefault("CRM_API_TOKEN", "test-crm-token")
os.environ.setdefault("CRM_ENCRYPTION_KEY", "00" * 32)
os.environ.setdefault("IS_SYNC_ENABLED", "false")
os.environ.setdefault("IS_CONSUMER_ENABLED", "false")
os.environ.setdefault("IS_WEBHOOK_ENABLED", "false")

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
            result = self.fetch_one_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
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


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> Self:
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None


class RecordingSession(FakeSession):
    """FakeSession that also records SQL (for code that builds its own SqlExecutor)."""

    def __init__(self, results: list[list[dict]] | None = None) -> None:
        super().__init__()
        self._results = results or []
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, query, values):
        self.statements.append((str(query), values))
        if self._results:
            return FakeResult(self._results.pop(0))
        return FakeResult([])


class RecordingSessionmaker:
    def __init__(self, results_per_session: list[list[list[dict]]]) -> None:
        self._results = results_per_session
        self.sessions: list[RecordingSession] = []

    def __call__(self) -> RecordingSession:
        results = self._results.pop(0) if self._results else []
        session = RecordingSession(results)
        self.sessions.append(session)
        return session


@pytest.fixture
def sql() -> FakeSqlExecutor:
    return FakeSqlExecutor()
