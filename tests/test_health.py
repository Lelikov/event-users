"""Tests for the /health (liveness) and /ready (readiness) endpoints."""

from typing import Self

from sqlalchemy.exc import OperationalError

from event_users import routes


class _FakeConnection:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def __aenter__(self) -> Self:
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:  # noqa: ARG002 — mirrors AsyncConnection.execute
        return None


class _FakeEngine:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._error)


class TestHealth:
    async def test_health_returns_ok(self) -> None:
        assert await routes.health() == {"status": "ok"}

    def test_routes_registered(self) -> None:
        paths = {route.path for route in routes.health_router.routes}

        assert "/health" in paths
        assert "/ready" in paths


class TestReady:
    async def test_ready_when_database_reachable(self) -> None:
        response = await routes.ready(engine=_FakeEngine())

        assert response.status_code == 200
        assert b'"status":"ready"' in response.body
        assert b'"database":true' in response.body

    async def test_not_ready_when_database_down(self) -> None:
        error = OperationalError("select 1", {}, Exception("connection refused"))

        response = await routes.ready(engine=_FakeEngine(error=error))

        assert response.status_code == 503
        assert b'"status":"not_ready"' in response.body
        assert b'"database":false' in response.body
