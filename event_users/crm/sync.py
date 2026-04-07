import asyncio
import base64
import json
from dataclasses import dataclass

import structlog
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_users.adapters.sql import SqlExecutor
from event_users.adapters.users_db import UsersDBAdapter
from event_users.crm.client import CrmClient, EncryptedUsersPayload
from event_users.dto.users import CreateUserContactDTO
from event_users.interfaces.users import IUsersDBAdapter


logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CrmUser:
    email: str
    name: str | None
    role: str
    time_zone: str | None = None
    contacts: list[CreateUserContactDTO] | None = None


def decrypt_payload(payload: EncryptedUsersPayload, key: bytes) -> list[CrmUser]:
    """Decrypt AES-256-CBC encrypted payload and parse the user list."""
    iv = base64.b64decode(payload.iv)
    ciphertext = base64.b64decode(payload.encrypted_data)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    raw: list[dict] = json.loads(plaintext.decode())
    return [
        CrmUser(
            email=item["email"],
            name=item.get("name"),
            role=item["role"],
            time_zone=item.get("time_zone"),
            contacts=[
                CreateUserContactDTO(channel=contact["channel"], contact_id=contact["contact_id"])
                for contact in (item.get("contacts") or [])
            ],
        )
        for item in raw
    ]


class CrmSyncService:
    def __init__(self, crm_client: CrmClient, db_adapter: IUsersDBAdapter, encryption_key: bytes) -> None:
        self._client = crm_client
        self._db = db_adapter
        self._key = encryption_key

    async def sync(self) -> None:
        logger.info("Starting CRM user sync")
        try:
            page = 1
            page_size = 100
            synced_total = 0

            while True:
                payload = await self._client.fetch_users(page=page, page_size=page_size)
                users = decrypt_payload(payload, self._key)
                logger.info(
                    "Decrypted CRM payload",
                    user_count=len(users),
                    page=payload.page,
                    page_size=payload.page_size,
                    total=payload.total,
                )

                for user in users:
                    await self._db.upsert_user_from_crm(
                        email=user.email,
                        role=user.role,
                        name=user.name,
                        time_zone=user.time_zone,
                        contacts=user.contacts,
                    )

                synced_total += len(users)
                if payload.page * payload.page_size >= payload.total:
                    break
                page += 1

            logger.info("CRM user sync completed", synced=synced_total)
        except Exception:
            logger.exception("CRM user sync failed")
            raise


class CrmSyncRunner:
    """Long-running background loop that syncs CRM users every `interval` seconds."""

    def __init__(
        self,
        crm_client: CrmClient,
        sessionmaker: async_sessionmaker[AsyncSession],
        encryption_key: bytes,
        interval: int,
    ) -> None:
        self._client = crm_client
        self._sessionmaker = sessionmaker
        self._key = encryption_key
        self._interval = interval

    async def run(self) -> None:
        while True:
            try:
                async with self._sessionmaker() as session:
                    db_adapter = UsersDBAdapter(sql_executor=SqlExecutor(session))
                    service = CrmSyncService(
                        crm_client=self._client,
                        db_adapter=db_adapter,
                        encryption_key=self._key,
                    )
                    await service.sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled error in CRM sync loop")
            await asyncio.sleep(self._interval)
