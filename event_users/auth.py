from __future__ import annotations
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from event_users.config import Settings


bearer_scheme = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    sub: str  # email
    role: str  # "admin" | "user"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def _check_static_token(token: str, settings: Settings) -> TokenPayload | None:
    if settings.api_bearer_token and token == settings.api_bearer_token:
        return TokenPayload(sub="api-token", role="admin")
    return None


def verify_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TokenPayload:
    settings = get_settings()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials

    # Try static API token first (cheap comparison before JWT decode)
    static = _check_static_token(token, settings)
    if static:
        return static

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
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
