import uuid

from event_users.webhook.sender import WebhookOutboxSender
from tests.conftest import RecordingSessionmaker


class FakeWebhookClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[dict] = []

    async def send(self, payload: dict) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(payload)


def outbox_row(attempts: int = 0, max_attempts: int = 5) -> dict:
    return {
        "id": uuid.uuid4(),
        "event_type": "user.email.changed",
        "payload": {"user_id": str(uuid.uuid4()), "old_email": "a@b.c", "new_email": "x@y.z"},
        "attempts": attempts,
        "max_attempts": max_attempts,
    }


def make_sender(rows: list[dict], client: FakeWebhookClient) -> tuple[WebhookOutboxSender, RecordingSessionmaker]:
    # session 1: claim returns rows; sessions 2..n: one per delivered row
    sessionmaker = RecordingSessionmaker([[rows]])
    sender = WebhookOutboxSender(
        sessionmaker=sessionmaker,  # type: ignore[arg-type]
        webhook_client=client,  # type: ignore[arg-type]
        batch_size=10,
        visibility_timeout=120,
    )
    return sender, sessionmaker


async def test_claim_commits_before_delivery_and_marks_processing() -> None:
    row = outbox_row()
    client = FakeWebhookClient()
    sender, sessionmaker = make_sender([row], client)

    await sender._process_batch()  # noqa: SLF001

    claim_session = sessionmaker.sessions[0]
    claim_query, claim_values = claim_session.statements[0]
    assert "SET status = 'processing'" in claim_query
    assert "FOR UPDATE SKIP LOCKED" in claim_query
    assert claim_values["visibility"] == 120
    assert claim_session.committed == 1  # claim published before any delivery

    assert client.sent == [row["payload"]]
    deliver_session = sessionmaker.sessions[1]
    deliver_query, deliver_values = deliver_session.statements[0]
    assert "status = 'delivered'" in deliver_query
    assert deliver_values["attempts"] == 1
    assert "email_source" not in deliver_query  # no premature guard reset
    assert deliver_session.committed == 1


async def test_failed_delivery_backs_off_to_pending() -> None:
    row = outbox_row(attempts=0)
    client = FakeWebhookClient(error=RuntimeError("CRM down"))
    sender, sessionmaker = make_sender([row], client)

    await sender._process_batch()  # noqa: SLF001

    deliver_session = sessionmaker.sessions[1]
    query, values = deliver_session.statements[0]
    assert "status = 'pending'" in query
    assert values["attempts"] == 1
    assert values["delay"] == 10  # 10 * attempts^2


async def test_exhausted_attempts_marks_failed() -> None:
    row = outbox_row(attempts=4, max_attempts=5)
    client = FakeWebhookClient(error=RuntimeError("CRM down"))
    sender, sessionmaker = make_sender([row], client)

    await sender._process_batch()  # noqa: SLF001

    deliver_session = sessionmaker.sessions[1]
    query, values = deliver_session.statements[0]
    assert "status = 'failed'" in query
    assert values["attempts"] == 5
