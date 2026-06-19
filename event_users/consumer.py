"""RabbitMQ consumer for user email change events."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from event_schemas.envelope import unwrap_payload
from event_schemas.queues import EVENTS_EXCHANGE, USER_EMAIL_QUEUE
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitMessage, RabbitQueue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_users.adapters.changelog_db import EmailChangelogDBAdapter
from event_users.adapters.sql import SqlExecutor
from event_users.adapters.sync_publisher import UserSyncedPublisher
from event_users.adapters.users_db import UsersDBAdapter
from event_users.dto.users import CreateUserContactDTO
from event_users.interfaces.cache_notifier import ICacheNotifier
from event_users.interfaces.sql import ISqlExecutor


logger = structlog.get_logger(__name__)


async def handle_email_change(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    cache_notifier: ICacheNotifier,
    user_id_str: str,
    old_email: str,
    new_email: str,
    requested_by: str,
    message_id: str | None = None,
) -> None:
    """Process email change in a single transaction (idempotent on ce-id)."""
    async with sessionmaker() as session:
        try:
            sql: ISqlExecutor = SqlExecutor(session)
            changelog_db = EmailChangelogDBAdapter(sql)

            user_id = uuid.UUID(user_id_str)

            # Idempotency gate first: the changelog insert conflicts on ce-id
            # for redelivered messages — skip everything (no duplicate webhook,
            # no phantom audit entry).
            inserted = await changelog_db.add_entry(
                user_id=user_id,
                old_email=old_email,
                new_email=new_email,
                changed_by=requested_by,
                message_id=message_id,
            )
            if not inserted:
                await session.rollback()
                logger.info(
                    "Email change message already processed, skipping",
                    user_id=user_id_str,
                    message_id=message_id,
                )
                return

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
            await cache_notifier.invalidate()
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


async def handle_user_upserted(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    sync_publisher: UserSyncedPublisher,
    email: str,
    role: str,
    time_zone: str | None,
    name: str | None,
    contacts: list,
    message_id: str | None,  # noqa: ARG001  (kept for call-site symmetry; ce-id is derived in the publisher)
) -> None:
    """Upsert a user from a db-sync ``user.upserted`` event, then emit ``user.synced`` after commit.

    cal.com is the source of truth; we upsert by (email, role) and publish the resulting
    ``user_id`` so event-saver can backfill bookings. Publish happens AFTER commit: a dropped
    publish is self-healing via the reconcile sweep + deterministic ce-id.
    """
    contact_dtos = [CreateUserContactDTO(channel=c["channel"], contact_id=c["contact_id"]) for c in contacts]
    async with sessionmaker() as session:
        adapter = UsersDBAdapter(SqlExecutor(session))
        user_id = await adapter.upsert_user_from_crm(
            email=email,
            role=role,
            time_zone=time_zone,
            name=name,
            contacts=contact_dtos,
        )
        await session.commit()
    await sync_publisher.publish(email=email, role=role, user_id=str(user_id), time_zone=time_zone)


class EmailChangeConsumer:
    """Manages RabbitMQ subscription for email change events."""

    def __init__(
        self,
        *,
        broker: RabbitBroker,
        sessionmaker: async_sessionmaker[AsyncSession],
        cache_notifier: ICacheNotifier,
        sync_publisher: UserSyncedPublisher,
    ) -> None:
        self._broker = broker
        self._sessionmaker = sessionmaker
        self._cache_notifier = cache_notifier
        self._sync_publisher = sync_publisher
        # Exchange + queue + binding come from the canonical topology in
        # event_schemas.queues (USER_EMAIL_QUEUE): declaring and binding here
        # makes the consumer independent of event-receiver's startup order —
        # on a fresh broker no user.email.* event is dropped.
        self._exchange = RabbitExchange(EVENTS_EXCHANGE, type=ExchangeType.TOPIC, durable=True)
        self._queue = RabbitQueue(
            USER_EMAIL_QUEUE.name,
            durable=True,
            routing_key=str(USER_EMAIL_QUEUE.binding),
            arguments=USER_EMAIL_QUEUE.arguments,
        )

    async def start(self) -> None:
        @self._broker.subscriber(self._queue, self._exchange)
        async def on_message(data: dict[str, Any], msg: RabbitMessage) -> None:
            headers = msg.headers or {}
            event_type = headers.get("ce-type", "")

            if event_type == "user.email.change_requested":
                original = unwrap_payload(data)
                await handle_email_change(
                    sessionmaker=self._sessionmaker,
                    cache_notifier=self._cache_notifier,
                    user_id_str=original["user_id"],
                    old_email=original["old_email"],
                    new_email=original["new_email"],
                    requested_by=original["requested_by"],
                    message_id=headers.get("ce-id"),
                )
                return

            if event_type == "user.upserted":
                original = unwrap_payload(data)
                await handle_user_upserted(
                    sessionmaker=self._sessionmaker,
                    sync_publisher=self._sync_publisher,
                    email=original["email"],
                    role=original["role"],
                    time_zone=original.get("time_zone"),
                    name=original.get("name"),
                    contacts=original.get("contacts", []),
                    message_id=headers.get("ce-id"),
                )
                return

            logger.warning("Unknown event type, skipping", event_type=event_type)

        await self._broker.start()
        logger.info("Email change consumer started")

    async def stop(self) -> None:
        await self._broker.close()
        logger.info("Email change consumer stopped")
