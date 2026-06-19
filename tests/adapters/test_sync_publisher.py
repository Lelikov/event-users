import json

from event_users.adapters.sync_publisher import UserSyncedPublisher


class FakeBroker:
    def __init__(self) -> None:
        self.calls = []

    async def publish(self, body, **kwargs) -> None:
        self.calls.append({"body": body, **kwargs})


async def test_publish_user_synced() -> None:
    broker = FakeBroker()
    pub = UserSyncedPublisher(broker=broker, exchange="events", publish_timeout=5.0)
    await pub.publish(email="a@b.c", role="client", user_id="550e8400-e29b-41d4-a716-446655440001", time_zone="UTC")
    call = broker.calls[0]
    assert call["routing_key"] == "events.user.synced"
    assert call["priority"] == 10
    assert call["headers"]["ce-type"] == "user.synced"
    assert call["headers"]["ce-source"] == "event-users"
    body = json.loads(call["body"])
    assert body["original"]["user_id"] == "550e8400-e29b-41d4-a716-446655440001"
    assert body["normalized"]["participants"] == []


async def test_publish_user_synced_deterministic_id() -> None:
    broker = FakeBroker()
    pub = UserSyncedPublisher(broker=broker, exchange="events", publish_timeout=5.0)
    kwargs = {"email": "a@b.c", "role": "client", "user_id": "550e8400-e29b-41d4-a716-446655440001", "time_zone": "UTC"}
    await pub.publish(**kwargs)
    await pub.publish(**kwargs)
    assert broker.calls[0]["headers"]["ce-id"] == broker.calls[1]["headers"]["ce-id"]
