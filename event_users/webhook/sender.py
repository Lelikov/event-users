"""Outbox poller that delivers webhook payloads to CRM."""

import asyncio
import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_users.adapters.sql import SqlExecutor
from event_users.webhook.client import CrmWebhookClient


logger = structlog.get_logger(__name__)


class WebhookOutboxSender:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        webhook_client: CrmWebhookClient,
        poll_interval: int = 1,
        batch_size: int = 10,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._webhook_client = webhook_client
        self._poll_interval = poll_interval
        self._batch_size = batch_size

    async def run(self) -> None:
        """Long-running loop: poll outbox, deliver, update status."""
        while True:
            try:
                await self._process_batch()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Webhook outbox poll failed")
            await asyncio.sleep(self._poll_interval)

    async def _process_batch(self) -> None:
        async with self._sessionmaker() as session:
            sql = SqlExecutor(session)

            rows = await sql.fetch_all(
                """
                SELECT id, event_type, payload, attempts, max_attempts
                FROM webhook_outbox
                WHERE status IN ('pending', 'processing')
                  AND next_retry_at <= now()
                ORDER BY created_at
                LIMIT :batch_size
                FOR UPDATE SKIP LOCKED
                """,
                {"batch_size": self._batch_size},
            )

            for row in rows:
                outbox_id = row["id"]
                attempts = row["attempts"] + 1
                payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])

                try:
                    await self._webhook_client.send(payload)
                    # Success: mark delivered and reset email_source
                    await sql.execute(
                        """
                        UPDATE webhook_outbox
                        SET status = 'delivered', delivered_at = now(), attempts = :attempts
                        WHERE id = :id
                        """,
                        {"id": outbox_id, "attempts": attempts},
                    )

                    # Reset email_source to 'crm' — CRM now has the new email
                    user_id = payload.get("user_id")
                    if user_id:
                        await sql.execute(
                            "UPDATE users SET email_source = 'crm' WHERE id = :user_id",
                            {"user_id": user_id},
                        )

                    logger.info("Webhook delivered", outbox_id=str(outbox_id))

                except Exception as exc:
                    error_msg = str(exc)[:500]
                    if attempts >= row["max_attempts"]:
                        await sql.execute(
                            """
                            UPDATE webhook_outbox
                            SET status = 'failed', attempts = :attempts, last_error = :error
                            WHERE id = :id
                            """,
                            {"id": outbox_id, "attempts": attempts, "error": error_msg},
                        )
                        logger.exception(
                            "Webhook permanently failed",
                            outbox_id=str(outbox_id),
                            attempts=attempts,
                        )
                    else:
                        delay_seconds = 10 * attempts * attempts
                        await sql.execute(
                            """
                            UPDATE webhook_outbox
                            SET status = 'pending',
                                attempts = :attempts,
                                last_error = :error,
                                next_retry_at = now() + make_interval(secs => :delay)
                            WHERE id = :id
                            """,
                            {
                                "id": outbox_id,
                                "attempts": attempts,
                                "error": error_msg,
                                "delay": delay_seconds,
                            },
                        )
                        logger.warning(
                            "Webhook delivery failed, will retry",
                            outbox_id=str(outbox_id),
                            attempts=attempts,
                            next_retry_seconds=delay_seconds,
                        )

                await session.commit()
