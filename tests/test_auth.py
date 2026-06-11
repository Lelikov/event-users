from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from event_users.auth import TokenPayload, _check_static_token, get_settings, require_admin, verify_bearer_token


def make_credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def make_jwt(role: str = "admin", **extra) -> str:
    settings = get_settings()
    claims = {"sub": "user@example.com", "role": role, "exp": datetime.now(UTC) + timedelta(minutes=5), **extra}
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_static_token_maps_to_admin() -> None:
    settings = get_settings()
    payload = _check_static_token("test-static-token", settings)
    assert payload is not None
    assert payload.role == "admin"


def test_static_token_rejects_wrong_value() -> None:
    settings = get_settings()
    assert _check_static_token("wrong", settings) is None


def test_verify_bearer_token_accepts_valid_jwt() -> None:
    payload = verify_bearer_token(make_credentials(make_jwt(role="user")))
    assert payload.sub == "user@example.com"
    assert payload.role == "user"


def test_verify_bearer_token_rejects_missing_credentials() -> None:
    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token(None)
    assert exc_info.value.status_code == 401


def test_verify_bearer_token_rejects_garbage() -> None:
    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token(make_credentials("not-a-jwt"))
    assert exc_info.value.status_code == 401


def test_verify_bearer_token_rejects_expired() -> None:
    settings = get_settings()
    token = jwt.encode(
        {"sub": "u@e.c", "role": "admin", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token(make_credentials(token))
    assert exc_info.value.status_code == 401


def test_verify_bearer_token_rejects_wrong_secret() -> None:
    token = jwt.encode({"sub": "u@e.c", "role": "admin"}, "other-secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token(make_credentials(token))
    assert exc_info.value.status_code == 401


def test_require_admin_allows_admin() -> None:
    user = TokenPayload(sub="a@b.c", role="admin")
    assert require_admin(user) is user


def test_require_admin_rejects_non_admin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_admin(TokenPayload(sub="a@b.c", role="user"))
    assert exc_info.value.status_code == 403


def _settings_with(monkeypatch, **overrides):
    patched = get_settings().model_copy(update=overrides)
    monkeypatch.setattr("event_users.auth.get_settings", lambda: patched)
    return patched


def test_audience_and_issuer_verified_when_configured(monkeypatch) -> None:
    settings = _settings_with(monkeypatch, jwt_audience="event-users", jwt_issuer="event-admin")
    token = jwt.encode(
        {
            "sub": "u@e.c",
            "role": "admin",
            "aud": "event-users",
            "iss": "event-admin",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    payload = verify_bearer_token(make_credentials(token))
    assert payload.role == "admin"


def test_wrong_audience_rejected_when_configured(monkeypatch) -> None:
    settings = _settings_with(monkeypatch, jwt_audience="event-users")
    token = jwt.encode(
        {"sub": "u@e.c", "role": "admin", "aud": "event-admin-ui", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token(make_credentials(token))
    assert exc_info.value.status_code == 401


def test_missing_audience_rejected_when_configured(monkeypatch) -> None:
    settings = _settings_with(monkeypatch, jwt_audience="event-users")
    token = jwt.encode(
        {"sub": "u@e.c", "role": "admin", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token(make_credentials(token))
    assert exc_info.value.status_code == 401


def test_audience_ignored_when_not_configured() -> None:
    # Backward tolerance: tokens with extra aud/iss claims still pass when binding is off.
    payload = verify_bearer_token(make_credentials(make_jwt(role="admin", aud="anything", iss="anyone")))
    assert payload.role == "admin"
