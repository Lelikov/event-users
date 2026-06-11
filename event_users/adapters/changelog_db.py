import json
import uuid

import structlog
from sqlalchemy.engine import RowMapping

from event_users.dto.changelog import EmailChangelogEntryDTO
from event_users.interfaces.sql import ISqlExecutor


logger = structlog.get_logger(__name__)


def _entry_from_row(row: RowMapping) -> EmailChangelogEntryDTO:
    return EmailChangelogEntryDTO(
        id=row["id"],
        old_email=row["old_email"],
        new_email=row["new_email"],
        changed_by=row["changed_by"],
        changed_at=row["changed_at"],
    )


class EmailChangelogDBAdapter:
    def __init__(self, sql_executor: ISqlExecutor) -> None:
        self._sql = sql_executor

    async def get_changelog(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[EmailChangelogEntryDTO], int]:
        count_row = await self._sql.fetch_one(
            "SELECT COUNT(*) AS total FROM user_email_changelog WHERE user_id = :user_id",
            {"user_id": user_id},
        )
        total: int = count_row["total"] if count_row else 0

        rows = await self._sql.fetch_all(
            """
            SELECT id, old_email, new_email, changed_by, changed_at
            FROM user_email_changelog
            WHERE user_id = :user_id
            ORDER BY changed_at DESC
            LIMIT :limit OFFSET :offset
            """,
            {"user_id": user_id, "limit": limit, "offset": offset},
        )
        return [_entry_from_row(r) for r in rows], total

    async def add_entry(
        self,
        *,
        user_id: uuid.UUID,
        old_email: str,
        new_email: str,
        changed_by: str,
        message_id: str | None = None,
    ) -> bool:
        """Insert a changelog entry.

        `message_id` (CloudEvent ce-id) is a unique idempotency key: a conflict
        means this message was already processed and False is returned so the
        caller can skip the rest of the work (NULL message_ids never conflict).
        """
        row = await self._sql.fetch_one(
            """
            INSERT INTO user_email_changelog (user_id, old_email, new_email, changed_by, message_id)
            VALUES (:user_id, :old_email, :new_email, :changed_by, :message_id)
            ON CONFLICT (message_id) DO NOTHING
            RETURNING id
            """,
            {
                "user_id": user_id,
                "old_email": old_email,
                "new_email": new_email,
                "changed_by": changed_by,
                "message_id": message_id,
            },
        )
        if row is None:
            logger.info("Duplicate email change message, changelog entry skipped", message_id=message_id)
            return False
        logger.info(
            "Email changelog entry added",
            user_id=str(user_id),
            old_email=old_email,
            new_email=new_email,
        )
        return True

    async def get_admin_changed_email_roles(self) -> set[tuple[str, str]]:
        """(old_email, role) pairs the CRM sync must not resurrect — one query per sync cycle."""
        rows = await self._sql.fetch_all(
            """
            SELECT DISTINCT c.old_email, u.role
            FROM user_email_changelog c
            JOIN users u ON u.id = c.user_id
            WHERE u.email_source = 'admin'
            """,
            {},
        )
        return {(row["old_email"], row["role"]) for row in rows}

    async def is_email_changed_by_admin(self, email: str, role: str) -> bool:
        """Check if this email was recently changed away from by an admin (for CRM sync protection)."""
        row = await self._sql.fetch_one(
            """
            SELECT 1 FROM user_email_changelog
            WHERE old_email = :email
              AND user_id IN (
                  SELECT id FROM users WHERE role = :role AND email_source = 'admin'
              )
            LIMIT 1
            """,
            {"email": email, "role": role},
        )
        return row is not None

    async def add_webhook_outbox(self, *, event_type: str, payload: dict) -> None:
        await self._sql.execute(
            """
            INSERT INTO webhook_outbox (event_type, payload)
            VALUES (:event_type, CAST(:payload AS jsonb))
            """,
            {"event_type": event_type, "payload": json.dumps(payload)},
        )
        logger.info("Webhook outbox entry added", event_type=event_type)
