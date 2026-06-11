import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from event_users.adapters.users_db import UsersDBAdapter
from event_users.dto.users import CreateUserDTO, UpdateUserDTO
from event_users.errors import ConflictError


NOW = datetime.now(UTC)


def user_row(user_id: uuid.UUID | None = None, email: str = "a@b.c", role: str = "client") -> dict:
    return {
        "id": user_id or uuid.uuid4(),
        "email": email,
        "name": None,
        "role": role,
        "time_zone": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def integrity_error() -> IntegrityError:
    return IntegrityError("duplicate key", params=None, orig=Exception("uq_users_email_role"))


def update_dto(**overrides) -> UpdateUserDTO:
    base = {"email": None, "name": None, "role": None, "time_zone": None, "contacts": None}
    return UpdateUserDTO(**{**base, **overrides})


async def test_update_user_raises_conflict_on_integrity_error(sql) -> None:
    adapter = UsersDBAdapter(sql)
    sql.fetch_one_results.append(integrity_error())

    with pytest.raises(ConflictError, match="already exists"):
        await adapter.update_user(uuid.uuid4(), update_dto(email="taken@b.c"))


async def test_update_user_returns_none_for_unknown_user(sql) -> None:
    adapter = UsersDBAdapter(sql)
    sql.fetch_one_results.append(None)

    result = await adapter.update_user(uuid.uuid4(), update_dto(name="New Name"))
    assert result is None


async def test_update_user_happy_path_updates_contacts(sql) -> None:
    user_id = uuid.uuid4()
    adapter = UsersDBAdapter(sql)
    sql.fetch_one_results.append(user_row(user_id))

    result = await adapter.update_user(user_id, update_dto(name="New Name"))

    assert result is not None
    update_statements = [q for q, _ in sql.statements if q.lstrip().startswith("UPDATE users")]
    assert len(update_statements) == 1


async def test_create_user_raises_conflict_on_integrity_error(sql) -> None:
    adapter = UsersDBAdapter(sql)
    sql.fetch_one_results.append(integrity_error())

    dto = CreateUserDTO(email="a@b.c", name=None, role="client", time_zone=None, contacts=[])
    with pytest.raises(ConflictError, match="already exists"):
        await adapter.create_user(dto)
