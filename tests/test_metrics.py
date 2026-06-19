"""Tests for the /metrics endpoint and HTTP RED middleware."""

from fastapi import FastAPI
from prometheus_client import REGISTRY
from starlette.testclient import TestClient

from event_users import metrics, routes


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint():
        return metrics.metrics_response()

    app.add_middleware(metrics.HttpMetricsMiddleware)
    return app


class TestMetricsEndpoint:
    def test_metrics_route_registered(self) -> None:
        paths = {route.path for route in routes.health_router.routes}

        assert "/metrics" in paths

    async def test_metrics_returns_prometheus_exposition(self) -> None:
        response = await routes.metrics_endpoint()

        assert response.status_code == 200
        assert response.media_type.startswith("text/plain")
        assert b"http_requests_total" in response.body


class TestHttpRedMiddleware:
    def test_counts_by_route_template_not_raw_path(self) -> None:
        client = TestClient(_build_app())
        labels = {"method": "GET", "route": "/items/{item_id}", "status": "200"}
        before = _sample("http_requests_total", labels)

        client.get("/items/42")

        assert _sample("http_requests_total", labels) == before + 1
        assert _sample("http_requests_total", {"method": "GET", "route": "/items/42", "status": "200"}) == 0.0

    def test_unmatched_route_recorded_as_unmatched(self) -> None:
        client = TestClient(_build_app())
        labels = {"method": "GET", "route": "unmatched", "status": "404"}
        before = _sample("http_requests_total", labels)

        client.get("/no/such/route")

        assert _sample("http_requests_total", labels) == before + 1

    def test_health_and_metrics_excluded(self) -> None:
        client = TestClient(_build_app())

        client.get("/health")
        client.get("/metrics")

        assert _sample("http_requests_total", {"method": "GET", "route": "/health", "status": "200"}) == 0.0
        assert _sample("http_requests_total", {"method": "GET", "route": "/metrics", "status": "200"}) == 0.0
