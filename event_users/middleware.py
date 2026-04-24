from __future__ import annotations
from typing import Any

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from event_users.auth import _check_static_token, get_settings


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer token (JWT or static API token) for every request except *public_paths*.

    OPTIONS requests are always passed through so CORS preflight works
    regardless of middleware ordering.
    """

    def __init__(self, app: ASGIApp, public_paths: frozenset[str] = frozenset()) -> None:
        super().__init__(app)
        self._public_paths = public_paths

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.method == "OPTIONS" or request.url.path in self._public_paths:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Missing bearer token"}, status_code=401)

        token = auth_header[7:]
        settings = get_settings()

        if _check_static_token(token, settings):
            return await call_next(request)

        try:
            jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        except jwt.ExpiredSignatureError:
            return JSONResponse({"detail": "Token expired"}, status_code=401)
        except jwt.InvalidTokenError, KeyError:
            return JSONResponse({"detail": "Invalid token"}, status_code=401)

        return await call_next(request)
