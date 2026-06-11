import uuid

import pytest

from event_users.controllers.users import UsersController
from event_users.dto.users import CreateUserDTO, UpdateUserDTO


class FakeUsersDB:
    def __init__(self) -> None:
        self.created: list[CreateUserDTO] = []
        self.updated: list[tuple[uuid.UUID, UpdateUserDTO]] = []

    async def create_user(self, dto: CreateUserDTO):
        self.created.append(dto)
        return dto

    async def update_user(self, user_id: uuid.UUID, dto: UpdateUserDTO) -> None:
        self.updated.append((user_id, dto))
        return None


def make_create_dto(time_zone: str | None) -> CreateUserDTO:
    return CreateUserDTO(email="a@b.c", name=None, role="client", time_zone=time_zone, contacts=[])


async def test_create_user_accepts_valid_timezone() -> None:
    db = FakeUsersDB()
    controller = UsersController(db)
    await controller.create_user(make_create_dto("Europe/Moscow"))
    assert len(db.created) == 1


async def test_create_user_rejects_invalid_timezone() -> None:
    controller = UsersController(FakeUsersDB())
    with pytest.raises(ValueError, match="Invalid time_zone"):
        await controller.create_user(make_create_dto("Mars/Olympus"))


async def test_create_user_allows_none_timezone() -> None:
    db = FakeUsersDB()
    controller = UsersController(db)
    await controller.create_user(make_create_dto(None))
    assert len(db.created) == 1


async def test_update_user_rejects_invalid_timezone() -> None:
    controller = UsersController(FakeUsersDB())
    dto = UpdateUserDTO(email=None, name=None, role=None, time_zone="Nope/Nope", contacts=None)
    with pytest.raises(ValueError, match="Invalid time_zone"):
        await controller.update_user(uuid.uuid4(), dto)
