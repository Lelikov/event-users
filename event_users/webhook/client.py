"""HTTP client for CRM webhook delivery."""

from typing import Any

import structlog
from httpx import AsyncClient


logger = structlog.get_logger(__name__)


class CrmWebhookClient:
    def __init__(self, *, http_client: AsyncClient, token: str) -> None:
        self._client = http_client
        self._token = token

    async def send(self, payload: dict[str, Any]) -> None:
        response = await self._client.post(
            "",
            json=payload,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        response.raise_for_status()
        logger.info("Webhook delivered to CRM", event_type=payload.get("event_type"))
