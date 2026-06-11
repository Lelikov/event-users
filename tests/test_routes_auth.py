"""Route-level auth: every /api/users route requires the admin role; /health is public."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from event_users.config import get_settings
from event_users.main import app


client = TestClient(app)


def make_jwt(role: str = "admin", **extra) -> str:
    settings = get_settings()
    claims = {"sub": "user@example.com", "role": role, "exp": datetime.now(UTC) + timedelta(minutes=5), **extra}
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


READ_ROUTES = [
    ("GET", "/api/users"),
    ("GET", "/api/users/id/8b3c9a52-0000-0000-0000-000000000000"),
    ("GET", "/api/users/roles/client/emails/a@b.c"),
    ("GET", "/api/users/8b3c9a52-0000-0000-0000-000000000000/email-changelog"),
    ("POST", "/api/users/by-ids"),
]


def test_health_is_public() -> None:
    response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.parametrize(("method", "path"), READ_ROUTES)
def test_read_routes_require_token(method: str, path: str) -> None:
    response = client.request(method, path)
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), READ_ROUTES)
def test_read_routes_reject_non_admin(method: str, path: str) -> None:
    response = client.request(method, path, headers={"Authorization": f"Bearer {make_jwt(role='user')}"})
    assert response.status_code == 403


def test_write_routes_reject_non_admin() -> None:
    headers = {"Authorization": f"Bearer {make_jwt(role='user')}"}
    assert client.post("/api/users", headers=headers).status_code == 403
    assert client.patch("/api/users/id/8b3c9a52-0000-0000-0000-000000000000", headers=headers).status_code == 403
