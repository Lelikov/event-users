import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.exc import IntegrityError

from event_users.dto.users import (
    CreateUserContactDTO,
    CreateUserDTO,
    ListUsersQueryDTO,
    UpdateUserDTO,
    UserContactDTO,
    UserDTO,
)
from event_users.errors import ConflictError
from event_users.interfaces.sql import ISqlExecutor


if TYPE_CHECKING:
    from sqlalchemy.engine import RowMapping


logger = structlog.get_logger(__name__)


def _contact_from_row(row: RowMapping) -> UserContactDTO:
    return UserContactDTO(
        id=row["id"],
        user_id=row["user_id"],
        channel=row["channel"],
        contact_id=row["contact_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _user_from_row(row: RowMapping, contacts: list[UserContactDTO]) -> UserDTO:
    return UserDTO(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        role=row["role"],
        time_zone=row["time_zone"],
        contacts=contacts,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class UsersDBAdapter:
    def __init__(self, sql_executor: ISqlExecutor) -> None:
        self._sql = sql_executor

    async def _fetch_contacts(self, user_id: uuid.UUID) -> list[UserContactDTO]:
        rows = await self._sql.fetch_all(
            """
            SELECT id, user_id, channel, contact_id, created_at, updated_at
            FROM user_contacts
            WHERE user_id = :user_id
            ORDER BY channel
            """,
            {"user_id": user_id},
        )
        return [_contact_from_row(r) for r in rows]

    async def create_user(self, dto: CreateUserDTO) -> UserDTO:
        try:
            row = await self._sql.fetch_one(
                """
                INSERT INTO users (email, name, role, time_zone)
                VALUES (:email, :name, :role, :time_zone)
                RETURNING id, email, name, role, time_zone, created_at, updated_at
                """,
                {"email": dto.email, "name": dto.name, "role": dto.role, "time_zone": dto.time_zone},
            )
        except IntegrityError as e:
            logger.info(
                "User create conflict",
                email=dto.email,
                role=dto.role,
            )
            raise ConflictError(f"User with email={dto.email!r} and role={dto.role!r} already exists") from e

        user_id: uuid.UUID = row["id"]

        await self._upsert_contacts(
            user_id,
            [*dto.contacts, CreateUserContactDTO(channel="email", contact_id=dto.email)],
        )

        contacts = await self._fetch_contacts(user_id)
        logger.info("User created", user_id=str(user_id), email=dto.email, role=dto.role)
        return _user_from_row(row, contacts)

    async def _upsert_contacts(self, user_id: uuid.UUID, contacts: list[CreateUserContactDTO]) -> None:
        for contact in contacts:
            await self._sql.execute(
                """
                INSERT INTO user_contacts (user_id, channel, contact_id)
                VALUES (:user_id, :channel, :contact_id)
                ON CONFLICT (user_id, channel)
                DO UPDATE SET contact_id = EXCLUDED.contact_id, updated_at = now()
                """,
                {"user_id": user_id, "channel": contact.channel, "contact_id": contact.contact_id},
            )

    async def update_user(self, user_id: uuid.UUID, dto: UpdateUserDTO) -> UserDTO | None:
        set_clauses: list[str] = []
        values: dict = {"user_id": user_id}

        if dto.email is not None:
            set_clauses.append("email = :email")
            values["email"] = dto.email
        if dto.name is not None:
            set_clauses.append("name = :name")
            values["name"] = dto.name
        if dto.role is not None:
            set_clauses.append("role = :role")
            values["role"] = dto.role
        if dto.time_zone is not None:
            set_clauses.append("time_zone = :time_zone")
            values["time_zone"] = dto.time_zone

        if set_clauses:
            set_clauses.append("updated_at = now()")
            row = await self._sql.fetch_one(
                f"""
                UPDATE users
                SET {", ".join(set_clauses)}
                WHERE id = :user_id
                RETURNING id, email, name, role, time_zone, created_at, updated_at
                """,  # noqa: S608
                values,
            )
            if row is None:
                return None
        else:
            row = await self._sql.fetch_one(
                "SELECT id, email, name, role, time_zone, created_at, updated_at FROM users WHERE id = :user_id",
                {"user_id": user_id},
            )
            if row is None:
                return None

        contacts_for_upsert: list[CreateUserContactDTO] = [
            *(dto.contacts or []),
            CreateUserContactDTO(channel="email", contact_id=row["email"]),
        ]
        await self._upsert_contacts(user_id, contacts_for_upsert)

        contacts = await self._fetch_contacts(user_id)
        logger.info("User updated", user_id=str(user_id))
        return _user_from_row(row, contacts)

    async def get_user(self, user_id: uuid.UUID) -> UserDTO | None:
        row = await self._sql.fetch_one(
            "SELECT id, email, name, role, time_zone, created_at, updated_at FROM users WHERE id = :user_id",
            {"user_id": user_id},
        )
        if row is None:
            return None
        contacts = await self._fetch_contacts(user_id)
        return _user_from_row(row, contacts)

    async def get_user_by_email_role(self, email: str, role: str) -> UserDTO | None:
        row = await self._sql.fetch_one(
            (
                "SELECT id, email, name, role, time_zone, created_at, updated_at "
                "FROM users WHERE email = :email AND role = :role"
            ),
            {"email": email, "role": role},
        )
        if row is None:
            return None
        contacts = await self._fetch_contacts(row["id"])
        return _user_from_row(row, contacts)

    async def list_users(self, query: ListUsersQueryDTO) -> tuple[list[UserDTO], int]:
        conditions: list[str] = []
        values: dict = {"limit": query.limit, "offset": query.offset}

        if query.email is not None:
            conditions.append("email ILIKE :email")
            values["email"] = f"%{query.email}%"
        if query.role is not None:
            conditions.append("role = :role")
            values["role"] = query.role

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_row = await self._sql.fetch_one(
            f"SELECT COUNT(*) AS total FROM users {where_clause}",  # noqa: S608
            values,
        )
        total: int = count_row["total"] if count_row else 0

        rows = await self._sql.fetch_all(
            f"""
            SELECT id, email, name, role, time_zone, created_at, updated_at
            FROM users
            {where_clause}
            ORDER BY created_at
            LIMIT :limit OFFSET :offset
            """,  # noqa: S608
            values,
        )

        users: list[UserDTO] = []
        for row in rows:
            contacts = await self._fetch_contacts(row["id"])
            users.append(_user_from_row(row, contacts))

        return users, total

    async def upsert_user_from_crm(
        self,
        email: str,
        role: str,
        time_zone: str | None,
        name: str | None = None,
        contacts: list[CreateUserContactDTO] | None = None,
    ) -> None:
        await self._sql.execute(
            """
            INSERT INTO users (email, name, role, time_zone)
            VALUES (:email, :name, :role, :time_zone)
            ON CONFLICT (email, role)
            DO UPDATE SET
                name = COALESCE(EXCLUDED.name, users.name),
                time_zone = COALESCE(EXCLUDED.time_zone, users.time_zone),
                updated_at = now()
            """,
            {"email": email, "name": name, "role": role, "time_zone": time_zone},
        )

        user_row = await self._sql.fetch_one(
            "SELECT id FROM users WHERE email = :email AND role = :role",
            {"email": email, "role": role},
        )
        if user_row is not None:
            contacts_for_upsert: list[CreateUserContactDTO] = [
                *(contacts or []),
                CreateUserContactDTO(channel="email", contact_id=email),
            ]
            await self._upsert_contacts(user_row["id"], contacts_for_upsert)

        logger.debug("User upserted from CRM", email=email, role=role)
