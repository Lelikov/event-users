from dataclasses import dataclass

import httpx
import structlog


logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EncryptedUsersPayload:
    encrypted_data: str  # base64-encoded ciphertext
    iv: str  # base64-encoded IV (16 bytes for AES-CBC)
    total: int
    page: int
    page_size: int


class CrmClient:
    def __init__(self, api_url: str, api_token: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}

    async def fetch_users(self, page: int = 1, page_size: int = 100) -> EncryptedUsersPayload:
        async with httpx.AsyncClient(timeout=30) as client:
            logger.info(
                "Fetching users from CRM",
                url=f"{self._api_url}/users",
                page=page,
                page_size=page_size,
            )
            response = await client.get(
                f"{self._api_url}/users",
                headers=self._headers,
                params={"page": page, "page_size": page_size},
            )
            response.raise_for_status()
            data = response.json()
            return EncryptedUsersPayload(
                encrypted_data=data["encrypted_data"],
                iv=data["iv"],
                total=data["total"],
                page=data["page"],
                page_size=data["page_size"],
            )
