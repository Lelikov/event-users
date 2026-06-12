import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_users import metrics
from event_users.adapters.changelog_db import EmailChangelogDBAdapter
from event_users.adapters.sql import SqlExecutor
from event_users.adapters.users_db import UsersDBAdapter
from event_users.crm.client import CrmClient, EncryptedUsersPayload
from event_users.dto.users import CreateUserContactDTO
from event_users.interfaces.changelog import IEmailChangelogDBAdapter
from event_users.interfaces.users import IUsersDBAdapter


logger = structlog.get_logger(__name__)


class CrmDecryptError(Exception):
    """The CRM payload could not be decrypted or parsed (wrong/rotated key, corrupted payload)."""


@dataclass(frozen=True)
class CrmUser:
    email: str
    name: str | None
    role: str
    time_zone: str | None = None
    contacts: list[CreateUserContactDTO] | None = None


@dataclass(frozen=True)
class DecryptedUsers:
    users: list[CrmUser]
    quarantined: int  # records that failed to parse and were skipped


@dataclass(frozen=True)
class SyncReport:
    synced: int
    skipped_admin_guard: int
    quarantined: int


def _parse_crm_user(item: dict) -> CrmUser:
    return CrmUser(
        email=item["email"],
        name=item.get("name"),
        role=item["role"],
        time_zone=item.get("time_zone"),
        contacts=[
            CreateUserContactDTO(channel=contact["channel"], contact_id=contact["contact_id"])
            for contact in (item.get("contacts") or [])
        ],
    )


def decrypt_payload(payload: EncryptedUsersPayload, key: bytes) -> DecryptedUsers:
    """Decrypt AES-256-CBC encrypted payload and parse the user list.

    Whole-payload failures (bad base64, bad padding from a wrong key, invalid
    JSON) raise CrmDecryptError so the sync cycle fails loudly. Individual
    malformed records are quarantined (skipped + counted) so one bad record
    cannot block the rest of the page.
    """
    try:
        iv = base64.b64decode(payload.iv)
        ciphertext = base64.b64decode(payload.encrypted_data)

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()

        raw = json.loads(plaintext.decode())
    except ValueError as exc:  # binascii.Error, bad padding, JSONDecodeError, UnicodeDecodeError
        raise CrmDecryptError("CRM payload decryption failed — wrong/rotated key or corrupted payload") from exc

    if not isinstance(raw, list):
        raise CrmDecryptError(f"CRM payload decrypted to {type(raw).__name__}, expected a list of users")

    users: list[CrmUser] = []
    quarantined = 0
    for index, item in enumerate(raw):
        try:
            users.append(_parse_crm_user(item))
        except (KeyError, TypeError, AttributeError):
            quarantined += 1
            logger.exception("Quarantined malformed CRM record", index=index, page=payload.page)
    return DecryptedUsers(users=users, quarantined=quarantined)


class CrmSyncService:
    def __init__(
        self,
        crm_client: CrmClient,
        session: AsyncSession,
        db_adapter: IUsersDBAdapter,
        changelog_adapter: IEmailChangelogDBAdapter,
        encryption_key: bytes,
    ) -> None:
        self._client = crm_client
        self._session = session
        self._db = db_adapter
        self._changelog = changelog_adapter
        self._key = encryption_key

    async def sync(self) -> SyncReport:
        logger.info("Starting CRM user sync")
        page = 1
        page_size = 100
        synced = 0
        skipped = 0
        quarantined = 0

        # One query per cycle instead of one guard query per user.
        guarded = await self._changelog.get_admin_changed_email_roles()

        while True:
            payload = await self._client.fetch_users(page=page, page_size=page_size)
            decrypted = decrypt_payload(payload, self._key)
            quarantined += decrypted.quarantined
            logger.info(
                "Decrypted CRM payload",
                user_count=len(decrypted.users),
                quarantined=decrypted.quarantined,
                page=payload.page,
                page_size=payload.page_size,
                total=payload.total,
            )

            for user in decrypted.users:
                # Skip users whose email was changed by admin (prevents duplicate creation)
                if (user.email, user.role) in guarded:
                    skipped += 1
                    logger.info(
                        "Skipping CRM upsert: email was changed by admin",
                        email=user.email,
                        role=user.role,
                    )
                    continue
                await self._db.upsert_user_from_crm(
                    email=user.email,
                    role=user.role,
                    name=user.name,
                    time_zone=user.time_zone,
                    contacts=user.contacts,
                )
                synced += 1

            # Commit per page: each page is one transaction, and a failure on a
            # later page never rolls back already-synced pages.
            await self._session.commit()

            if payload.page * payload.page_size >= payload.total:
                break
            page += 1

        report = SyncReport(synced=synced, skipped_admin_guard=skipped, quarantined=quarantined)
        metrics.CRM_SYNC_RECORDS_TOTAL.labels(outcome="synced").inc(report.synced)
        metrics.CRM_SYNC_RECORDS_TOTAL.labels(outcome="skipped_admin_guard").inc(report.skipped_admin_guard)
        metrics.CRM_SYNC_RECORDS_TOTAL.labels(outcome="quarantined").inc(report.quarantined)
        logger.info(
            "CRM user sync completed",
            synced=report.synced,
            skipped_admin_guard=report.skipped_admin_guard,
            quarantined=report.quarantined,
        )
        return report


class CrmSyncRunner:
    """Long-running background loop that syncs CRM users every `interval` seconds.

    Repeated failures back off exponentially (interval * 2^failures, capped at
    `max_backoff`) instead of hammering a broken CRM at a fixed cadence.
    """

    def __init__(
        self,
        crm_client: CrmClient,
        sessionmaker: async_sessionmaker[AsyncSession],
        encryption_key: bytes,
        interval: int,
        max_backoff: int = 1800,
    ) -> None:
        self._client = crm_client
        self._sessionmaker = sessionmaker
        self._key = encryption_key
        self._interval = interval
        self._max_backoff = max_backoff
        self.last_success_at: datetime | None = None
        self.consecutive_failures = 0

    def next_delay(self) -> int:
        if self.consecutive_failures == 0:
            return self._interval
        backoff = self._interval * (2 ** min(self.consecutive_failures, 16))
        return min(backoff, self._max_backoff)

    async def _run_once(self) -> None:
        async with self._sessionmaker() as session:
            sql_executor = SqlExecutor(session)
            service = CrmSyncService(
                crm_client=self._client,
                session=session,
                db_adapter=UsersDBAdapter(sql_executor=sql_executor),
                changelog_adapter=EmailChangelogDBAdapter(sql_executor=sql_executor),
                encryption_key=self._key,
            )
            await service.sync()

    async def run(self) -> None:
        while True:
            try:
                await self._run_once()
                self.consecutive_failures = 0
                self.last_success_at = datetime.now(UTC)
                metrics.CRM_SYNC_CYCLES_TOTAL.labels(outcome="ok").inc()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.consecutive_failures += 1
                metrics.CRM_SYNC_CYCLES_TOTAL.labels(outcome="error").inc()
                logger.exception(
                    "CRM sync cycle failed",
                    consecutive_failures=self.consecutive_failures,
                    next_retry_seconds=self.next_delay(),
                    last_success_at=self.last_success_at.isoformat() if self.last_success_at else None,
                )
            await asyncio.sleep(self.next_delay())
