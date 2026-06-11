from __future__ import annotations
import hmac
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from event_users.config import Settings, get_settings


bearer_scheme = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    sub: str  # email
    role: str  # "admin" | "user"


def _check_static_token(token: str, settings: Settings) -> TokenPayload | None:
    if settings.api_bearer_token and hmac.compare_digest(token, settings.api_bearer_token):
        return TokenPayload(sub="api-token", role="admin")
    return None


def _decode_jwt(token: str, settings: Settings) -> dict[str, Any]:
    # When no audience is configured, tokens carrying an aud claim must still
    # pass (rollout tolerance while event-admin starts minting aud/iss).
    kwargs: dict[str, Any] = {"options": {"verify_aud": bool(settings.jwt_audience)}}
    if settings.jwt_audience:
        kwargs["audience"] = settings.jwt_audience
    if settings.jwt_issuer:
        kwargs["issuer"] = settings.jwt_issuer
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        **kwargs,
    )


def verify_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TokenPayload:
    """Single decode path for all routes: static service token or HS256 JWT."""
    settings = get_settings()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials

    static = _check_static_token(token, settings)
    if static:
        return static

    try:
        payload = _decode_jwt(token, settings)
        return TokenPayload(sub=payload["sub"], role=payload["role"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except (jwt.InvalidTokenError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def require_admin(
    user: Annotated[TokenPayload, Depends(verify_bearer_token)],
) -> TokenPayload:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
