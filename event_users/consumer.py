"""RabbitMQ consumer for user email change events."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_users.adapters.changelog_db import EmailChangelogDBAdapter
from event_users.adapters.sql import SqlExecutor
from event_users.interfaces.sql import ISqlExecutor


logger = structlog.get_logger(__name__)


async def handle_email_change(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id_str: str,
    old_email: str,
    new_email: str,
    requested_by: str,
) -> None:
    """Process email change in a single transaction."""
    async with sessionmaker() as session:
        try:
            sql: ISqlExecutor = SqlExecutor(session)
            changelog_db = EmailChangelogDBAdapter(sql)

            user_id = uuid.UUID(user_id_str)

            # Update user email and set email_source = 'admin'
            await sql.execute(
                """
                UPDATE users
                SET email = :new_email, email_source = 'admin', updated_at = now()
                WHERE id = :user_id
                """,
                {"new_email": new_email, "user_id": user_id},
            )

            # Update email contact
            await sql.execute(
                """
                INSERT INTO user_contacts (user_id, channel, contact_id)
                VALUES (:user_id, 'email', :new_email)
                ON CONFLICT (user_id, channel)
                DO UPDATE SET contact_id = EXCLUDED.contact_id, updated_at = now()
                """,
                {"user_id": user_id, "new_email": new_email},
            )

            # Add changelog entry
            await changelog_db.add_entry(
                user_id=user_id,
                old_email=old_email,
                new_email=new_email,
                changed_by=requested_by,
            )

            # Add webhook outbox entry
            await changelog_db.add_webhook_outbox(
                event_type="user.email.changed",
                payload={
                    "user_id": user_id_str,
                    "old_email": old_email,
                    "new_email": new_email,
                    "changed_at": datetime.now(UTC).isoformat(),
                },
            )

            await session.commit()
            logger.info(
                "Email change processed",
                user_id=user_id_str,
                old_email=old_email,
                new_email=new_email,
            )
        except Exception:
            await session.rollback()
            logger.exception(
                "Email change failed",
                user_id=user_id_str,
            )
            raise


class EmailChangeConsumer:
    """Manages RabbitMQ subscription for email change events."""

    def __init__(
        self,
        *,
        broker: RabbitBroker,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self._broker = broker
        self._sessionmaker = sessionmaker
        self._queue = RabbitQueue(
            "events.user.email",
            durable=True,
            arguments={
                "x-max-priority": 10,
                "x-dead-letter-exchange": "events.dlx",
                "x-dead-letter-routing-key": "events.user.email.dlq",
            },
        )

    async def start(self) -> None:
        @self._broker.subscriber(self._queue)
        async def on_message(data: dict[str, Any], msg: RabbitMessage) -> None:
            headers = msg.headers or {}
            event_type = headers.get("ce-type", "")

            if event_type != "user.email.change_requested":
                logger.warning("Unknown event type, skipping", event_type=event_type)
                return

            # CloudEvents binary mode: data is the deserialized JSON body,
            # event metadata is in AMQP headers (ce-type, ce-source, etc.)
            await handle_email_change(
                sessionmaker=self._sessionmaker,
                user_id_str=data["user_id"],
                old_email=data["old_email"],
                new_email=data["new_email"],
                requested_by=data["requested_by"],
            )

        await self._broker.start()
        logger.info("Email change consumer started")

    async def stop(self) -> None:
        await self._broker.close()
        logger.info("Email change consumer stopped")
