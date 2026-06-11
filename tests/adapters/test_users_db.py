import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from event_users.adapters.users_db import UsersDBAdapter
from event_users.dto.users import CreateUserContactDTO, CreateUserDTO, UpdateUserDTO
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


async def test_upsert_user_from_crm_flips_email_source_on_convergence(sql) -> None:
    adapter = UsersDBAdapter(sql)
    sql.fetch_one_results.append({"id": uuid.uuid4()})

    await adapter.upsert_user_from_crm(email="a@b.c", role="client", time_zone=None)

    upsert_query, _ = sql.statements[0]
    assert "RETURNING id" in upsert_query
    assert "email_source = 'crm'" in upsert_query  # convergence disarms the admin guard
    assert "WHERE users.email_source" not in upsert_query


async def test_upsert_user_from_crm_batches_contacts_into_one_statement(sql) -> None:
    adapter = UsersDBAdapter(sql)
    user_id = uuid.uuid4()
    sql.fetch_one_results.append({"id": user_id})

    contacts = [
        CreateUserContactDTO(channel="telegram", contact_id="123"),
        CreateUserContactDTO(channel="push", contact_id="tok"),
    ]
    await adapter.upsert_user_from_crm(email="a@b.c", role="client", time_zone=None, contacts=contacts)

    contact_statements = [(q, v) for q, v in sql.statements if "user_contacts" in q]
    assert len(contact_statements) == 1
    _, values = contact_statements[0]
    assert values["channels"] == ["telegram", "push", "email"]
    assert values["contact_ids"] == ["123", "tok", "a@b.c"]
