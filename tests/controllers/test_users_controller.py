import uuid
from datetime import UTC, datetime

import pytest

from event_users.controllers.users import UsersController
from event_users.dto.users import CreateUserDTO, UpdateUserDTO, UserDTO


def make_user_dto(user_id: uuid.UUID, email: str = "a@b.c") -> UserDTO:
    now = datetime.now(UTC)
    return UserDTO(
        id=user_id,
        email=email,
        name=None,
        role="client",
        time_zone=None,
        contacts=[],
        created_at=now,
        updated_at=now,
    )


class FakeUsersDB:
    def __init__(self, existing: UserDTO | None = None) -> None:
        self.existing = existing
        self.created: list[CreateUserDTO] = []
        self.updated: list[tuple[uuid.UUID, UpdateUserDTO, bool]] = []

    async def create_user(self, dto: CreateUserDTO):
        self.created.append(dto)
        return dto

    async def get_user(self, user_id: uuid.UUID) -> UserDTO | None:  # noqa: ARG002
        return self.existing

    async def update_user(
        self,
        user_id: uuid.UUID,
        dto: UpdateUserDTO,
        *,
        mark_email_admin: bool = False,
    ) -> UserDTO | None:
        self.updated.append((user_id, dto, mark_email_admin))
        if self.existing is None:
            return None
        return make_user_dto(user_id, email=dto.email or self.existing.email)


class FakeChangelog:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.outbox: list[dict] = []

    async def add_entry(self, *, user_id: uuid.UUID, old_email: str, new_email: str, changed_by: str) -> None:
        self.entries.append(
            {"user_id": user_id, "old_email": old_email, "new_email": new_email, "changed_by": changed_by},
        )

    async def add_webhook_outbox(self, *, event_type: str, payload: dict) -> None:
        self.outbox.append({"event_type": event_type, "payload": payload})


def make_controller(db: FakeUsersDB | None = None) -> tuple[UsersController, FakeUsersDB, FakeChangelog]:
    db = db or FakeUsersDB()
    changelog = FakeChangelog()
    return UsersController(db, changelog), db, changelog


def make_create_dto(time_zone: str | None) -> CreateUserDTO:
    return CreateUserDTO(email="a@b.c", name=None, role="client", time_zone=time_zone, contacts=[])


def make_update_dto(email: str | None = None, time_zone: str | None = None) -> UpdateUserDTO:
    return UpdateUserDTO(email=email, name=None, role=None, time_zone=time_zone, contacts=None)


async def test_create_user_accepts_valid_timezone() -> None:
    controller, db, _ = make_controller()
    await controller.create_user(make_create_dto("Europe/Moscow"))
    assert len(db.created) == 1


async def test_create_user_rejects_invalid_timezone() -> None:
    controller, _, _ = make_controller()
    with pytest.raises(ValueError, match="Invalid time_zone"):
        await controller.create_user(make_create_dto("Mars/Olympus"))


async def test_create_user_allows_none_timezone() -> None:
    controller, db, _ = make_controller()
    await controller.create_user(make_create_dto(None))
    assert len(db.created) == 1


async def test_update_user_rejects_invalid_timezone() -> None:
    controller, _, _ = make_controller()
    with pytest.raises(ValueError, match="Invalid time_zone"):
        await controller.update_user(uuid.uuid4(), make_update_dto(time_zone="Nope/Nope"))


async def test_update_without_email_skips_changelog() -> None:
    user_id = uuid.uuid4()
    controller, db, changelog = make_controller(FakeUsersDB(existing=make_user_dto(user_id)))
    await controller.update_user(user_id, make_update_dto(time_zone="Europe/Moscow"))
    assert db.updated == [(user_id, make_update_dto(time_zone="Europe/Moscow"), False)]
    assert changelog.entries == []
    assert changelog.outbox == []


async def test_update_with_same_email_skips_changelog() -> None:
    user_id = uuid.uuid4()
    controller, db, changelog = make_controller(FakeUsersDB(existing=make_user_dto(user_id, email="a@b.c")))
    await controller.update_user(user_id, make_update_dto(email="a@b.c"))
    assert db.updated[0][2] is False
    assert changelog.entries == []
    assert changelog.outbox == []


async def test_update_with_email_change_writes_changelog_outbox_and_marks_admin() -> None:
    user_id = uuid.uuid4()
    controller, db, changelog = make_controller(FakeUsersDB(existing=make_user_dto(user_id, email="old@b.c")))
    result = await controller.update_user(user_id, make_update_dto(email="new@b.c"), changed_by="admin@x.y")

    assert result is not None
    assert db.updated[0][2] is True  # mark_email_admin arms the CRM-sync guard
    assert changelog.entries == [
        {"user_id": user_id, "old_email": "old@b.c", "new_email": "new@b.c", "changed_by": "admin@x.y"},
    ]
    assert len(changelog.outbox) == 1
    assert changelog.outbox[0]["event_type"] == "user.email.changed"
    payload = changelog.outbox[0]["payload"]
    assert payload["user_id"] == str(user_id)
    assert payload["old_email"] == "old@b.c"
    assert payload["new_email"] == "new@b.c"


async def test_update_with_email_change_missing_user_returns_none() -> None:
    controller, _, changelog = make_controller(FakeUsersDB(existing=None))
    result = await controller.update_user(uuid.uuid4(), make_update_dto(email="new@b.c"))
    assert result is None
    assert changelog.entries == []
    assert changelog.outbox == []
