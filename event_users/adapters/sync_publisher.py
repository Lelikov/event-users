import json
import uuid
from typing import Protocol

from cloudevents.core.bindings.http import to_binary
from cloudevents.core.formats.json import JSONFormat
from cloudevents.core.v1.event import CloudEvent
from event_schemas.queues import RoutingKey
from event_schemas.types import EVENT_PRIORITIES, EventType
from event_schemas.user import UserSyncedPayload


_SOURCE = "event-users"
_EVENT_TYPE = EventType.USER_SYNCED
_NAMESPACE = uuid.UUID("0b6d2c2e-9f3a-5e7b-8c1d-2f4a6b8c0e10")


class IBroker(Protocol):
    async def publish(self, body: bytes, **kwargs: object) -> None: ...


class UserSyncedPublisher:
    """Builds a binary-mode ``user.synced`` CloudEvent and publishes it straight to the ``events`` exchange.

    Wire-compatible with event-receiver: same ``to_binary(event, JSONFormat())`` form, so headers come out
    as lowercase ``ce-*`` keys. The ``ce-id`` is deterministic (``uuid5`` over ``role:email:user_id``) so
    redelivery collapses to one logical event downstream. The mandatory ``{original, normalized}`` envelope
    wraps the payload — consumers unwrap ``original``.
    """

    def __init__(self, broker: IBroker, exchange: str, publish_timeout: float) -> None:
        self._broker = broker
        self._exchange = exchange
        self._timeout = publish_timeout

    async def publish(self, *, email: str, role: str, user_id: str, time_zone: str | None) -> None:
        payload = UserSyncedPayload(email=email, role=role, user_id=str(user_id), time_zone=time_zone)
        envelope = {"original": payload.model_dump(mode="json"), "normalized": {"participants": []}}
        key = f"{role}:{email}:{user_id}"
        event = CloudEvent(
            attributes={
                "type": str(_EVENT_TYPE),
                "source": _SOURCE,
                "id": str(uuid.uuid5(_NAMESPACE, key)),
                "specversion": "1.0",
            },
            data=json.dumps(envelope).encode(),
        )
        message = to_binary(event, JSONFormat())
        headers = dict(message.headers)
        headers["content-type"] = "application/json"
        await self._broker.publish(
            message.body,
            exchange=self._exchange,
            routing_key=str(RoutingKey.USER_SYNCED),
            headers=headers,
            content_type="application/json",
            message_type=str(_EVENT_TYPE),
            priority=EVENT_PRIORITIES[_EVENT_TYPE].value,
            timeout=self._timeout,
        )
