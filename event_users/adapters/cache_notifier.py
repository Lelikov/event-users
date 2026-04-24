"""Notifies event-admin to invalidate its users cache."""

import structlog
from httpx import AsyncClient


logger = structlog.get_logger(__name__)


class CacheNotifier:
    def __init__(self, *, http_client: AsyncClient, token: str) -> None:
        self._client = http_client
        self._headers = {"Authorization": f"Bearer {token}"}

    async def invalidate(self) -> None:
        try:
            response = await self._client.post("/api/users/cache/invalidate", headers=self._headers)
            response.raise_for_status()
            logger.info("event-admin users cache invalidated")
        except Exception:
            logger.exception("Failed to invalidate event-admin users cache")
