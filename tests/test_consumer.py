import uuid

from event_users.consumer import handle_email_change, handle_user_upserted
from tests.conftest import RecordingSessionmaker


class FakeNotifier:
    def __init__(self) -> None:
        self.invalidations = 0

    async def invalidate(self) -> None:
        self.invalidations += 1


async def test_email_change_processes_once_and_invalidates_after_commit() -> None:
    user_id = uuid.uuid4()
    # First fetch_one: changelog INSERT ... RETURNING id succeeds
    sessionmaker = RecordingSessionmaker([[[{"id": uuid.uuid4()}]]])
    notifier = FakeNotifier()

    await handle_email_change(
        sessionmaker=sessionmaker,  # type: ignore[arg-type]
        cache_notifier=notifier,  # type: ignore[arg-type]
        user_id_str=str(user_id),
        old_email="old@b.c",
        new_email="new@b.c",
        requested_by="admin@x.y",
        message_id="ce-id-1",
    )

    session = sessionmaker.sessions[0]
    queries = [q for q, _ in session.statements]
    assert any("INSERT INTO user_email_changelog" in q for q in queries)
    assert any("UPDATE users" in q for q in queries)
    assert any("INSERT INTO user_contacts" in q for q in queries)
    assert any("INSERT INTO webhook_outbox" in q for q in queries)
    assert session.committed == 1
    assert notifier.invalidations == 1

    changelog_values = next(v for q, v in session.statements if "user_email_changelog" in q)
    assert changelog_values["message_id"] == "ce-id-1"


async def test_redelivered_message_is_skipped_entirely() -> None:
    # Changelog INSERT conflicts on message_id -> RETURNING yields no row
    sessionmaker = RecordingSessionmaker([[[]]])
    notifier = FakeNotifier()

    await handle_email_change(
        sessionmaker=sessionmaker,  # type: ignore[arg-type]
        cache_notifier=notifier,  # type: ignore[arg-type]
        user_id_str=str(uuid.uuid4()),
        old_email="old@b.c",
        new_email="new@b.c",
        requested_by="admin@x.y",
        message_id="ce-id-dup",
    )

    session = sessionmaker.sessions[0]
    queries = [q for q, _ in session.statements]
    assert len([q for q in queries if "user_email_changelog" in q]) == 1
    assert not any("UPDATE users" in q for q in queries)
    assert not any("webhook_outbox" in q for q in queries)
    assert session.committed == 0
    assert notifier.invalidations == 0


class FakeSyncPublisher:
    def __init__(self) -> None:
        self.published = []

    async def publish(self, *, email, role, user_id, time_zone) -> None:
        self.published.append((email, role, str(user_id), time_zone))


async def test_user_upserted_upserts_then_publishes_synced() -> None:
    new_id = uuid.uuid4()
    sessionmaker = RecordingSessionmaker([[[{"id": new_id}], []]])
    publisher = FakeSyncPublisher()
    await handle_user_upserted(
        sessionmaker=sessionmaker,  # type: ignore[arg-type]
        sync_publisher=publisher,  # type: ignore[arg-type]
        email="c@ex.com",
        role="client",
        time_zone="UTC",
        name="C",
        contacts=[],
        message_id="ce-1",
    )
    session = sessionmaker.sessions[0]
    queries = [q for q, _ in session.statements]
    assert any("INSERT INTO users" in q for q in queries)
    assert session.committed == 1
    assert publisher.published == [("c@ex.com", "client", str(new_id), "UTC")]
