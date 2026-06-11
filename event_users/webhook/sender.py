"""Outbox poller that delivers webhook payloads to CRM.

Two-phase processing so multiple replicas never deliver the same row twice:

1. CLAIM (one transaction): atomically flip a batch of due rows to
   status='processing' and push next_retry_at forward by the visibility
   timeout, using FOR UPDATE SKIP LOCKED inside a single UPDATE. The commit
   publishes the claim — other pollers skip the rows until the timeout.
2. DELIVER (per row, own transaction): POST to CRM, then finalize the row
   (delivered / pending-with-backoff / failed). A crash between claim and
   finalize leaves the row in 'processing'; it becomes claimable again once
   the visibility timeout elapses.
"""

import asyncio
import json

import structlog
from sqlalchemy.engine import RowMapping
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
        visibility_timeout: int = 120,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._webhook_client = webhook_client
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._visibility_timeout = visibility_timeout

    async def run(self) -> None:
        """Long-running loop: claim a batch, deliver, finalize."""
        while True:
            try:
                await self._process_batch()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Webhook outbox poll failed")
            await asyncio.sleep(self._poll_interval)

    async def _claim_batch(self) -> list[RowMapping]:
        async with self._sessionmaker() as session:
            sql = SqlExecutor(session)
            rows = await sql.fetch_all(
                """
                UPDATE webhook_outbox
                SET status = 'processing',
                    next_retry_at = now() + make_interval(secs => :visibility)
                WHERE id IN (
                    SELECT id
                    FROM webhook_outbox
                    WHERE status IN ('pending', 'processing')
                      AND next_retry_at <= now()
                    ORDER BY created_at
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, event_type, payload, attempts, max_attempts
                """,
                {"batch_size": self._batch_size, "visibility": self._visibility_timeout},
            )
            await session.commit()
            return rows

    async def _process_batch(self) -> None:
        rows = await self._claim_batch()
        for row in rows:
            await self._deliver_row(row)

    async def _deliver_row(self, row: RowMapping) -> None:
        outbox_id = row["id"]
        attempts = row["attempts"] + 1
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])

        async with self._sessionmaker() as session:
            sql = SqlExecutor(session)
            try:
                await self._webhook_client.send(payload)
                # Success: mark delivered. email_source is NOT reset here —
                # a 2xx only means the CRM received the webhook, not that its
                # /users export reflects the new email. The CRM sync flips
                # email_source back to 'crm' once the export converges
                # (upsert_user_from_crm conflict on the new email).
                await sql.execute(
                    """
                    UPDATE webhook_outbox
                    SET status = 'delivered', delivered_at = now(), attempts = :attempts
                    WHERE id = :id
                    """,
                    {"id": outbox_id, "attempts": attempts},
                )
                logger.info("Webhook delivered", outbox_id=str(outbox_id))
            except Exception as exc:  # noqa: BLE001 — any delivery error goes through retry accounting
                await self._record_failure(sql, outbox_id, attempts, row["max_attempts"], exc)
            await session.commit()

    async def _record_failure(
        self,
        sql: SqlExecutor,
        outbox_id: object,
        attempts: int,
        max_attempts: int,
        exc: Exception,
    ) -> None:
        error_msg = str(exc)[:500]
        if attempts >= max_attempts:
            await sql.execute(
                """
                UPDATE webhook_outbox
                SET status = 'failed', attempts = :attempts, last_error = :error
                WHERE id = :id
                """,
                {"id": outbox_id, "attempts": attempts, "error": error_msg},
            )
            logger.exception("Webhook permanently failed", outbox_id=str(outbox_id), attempts=attempts)
            return

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
            {"id": outbox_id, "attempts": attempts, "error": error_msg, "delay": delay_seconds},
        )
        logger.warning(
            "Webhook delivery failed, will retry",
            outbox_id=str(outbox_id),
            attempts=attempts,
            next_retry_seconds=delay_seconds,
        )
