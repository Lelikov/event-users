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
        if not contacts:
            return
        # One statement for the whole batch; dedupe by channel (last wins) so a
        # single INSERT cannot touch the same (user_id, channel) row twice.
        by_channel: dict[str, str] = {contact.channel: contact.contact_id for contact in contacts}
        await self._sql.execute(
            """
            INSERT INTO user_contacts (user_id, channel, contact_id)
            SELECT :user_id, t.channel, t.contact_id
            FROM unnest(CAST(:channels AS text[]), CAST(:contact_ids AS text[])) AS t(channel, contact_id)
            ON CONFLICT (user_id, channel)
            DO UPDATE SET contact_id = EXCLUDED.contact_id, updated_at = now()
            """,
            {"user_id": user_id, "channels": list(by_channel), "contact_ids": list(by_channel.values())},
        )

    async def update_user(
        self,
        user_id: uuid.UUID,
        dto: UpdateUserDTO,
        *,
        mark_email_admin: bool = False,
    ) -> UserDTO | None:
        row = await self._apply_update(user_id, dto, mark_email_admin=mark_email_admin)
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

    async def _apply_update(
        self,
        user_id: uuid.UUID,
        dto: UpdateUserDTO,
        *,
        mark_email_admin: bool = False,
    ) -> RowMapping | None:
        set_clauses: list[str] = []
        values: dict = {"user_id": user_id}

        if dto.email is not None:
            set_clauses.append("email = :email")
            values["email"] = dto.email
        if mark_email_admin:
            # Email changed via the admin API: arm the CRM-sync guard so the
            # next sync cannot resurrect the old email as a duplicate user.
            set_clauses.append("email_source = 'admin'")
        if dto.name is not None:
            set_clauses.append("name = :name")
            values["name"] = dto.name
        if dto.role is not None:
            set_clauses.append("role = :role")
            values["role"] = dto.role
        if dto.time_zone is not None:
            set_clauses.append("time_zone = :time_zone")
            values["time_zone"] = dto.time_zone

        if not set_clauses:
            return await self._sql.fetch_one(
                "SELECT id, email, name, role, time_zone, created_at, updated_at FROM users WHERE id = :user_id",
                {"user_id": user_id},
            )

        set_clauses.append("updated_at = now()")
        try:
            return await self._sql.fetch_one(
                f"""
                UPDATE users
                SET {", ".join(set_clauses)}
                WHERE id = :user_id
                RETURNING id, email, name, role, time_zone, created_at, updated_at
                """,  # noqa: S608
                values,
            )
        except IntegrityError as e:
            logger.info("User update conflict", user_id=str(user_id), email=dto.email, role=dto.role)
            raise ConflictError(
                f"User with email={dto.email!r} and role={dto.role!r} already exists",
            ) from e

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
            # Escape ILIKE metacharacters: '_' is legal in email local parts and
            # '%'/'\' must not act as wildcards in a user-supplied search term.
            escaped = query.email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("email ILIKE :email ESCAPE '\\'")
            values["email"] = f"%{escaped}%"
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

        user_ids = [row["id"] for row in rows]
        contacts_by_user: dict[uuid.UUID, list[UserContactDTO]] = {uid: [] for uid in user_ids}

        if user_ids:
            contact_rows = await self._sql.fetch_all(
                """
                SELECT id, user_id, channel, contact_id, created_at, updated_at
                FROM user_contacts
                WHERE user_id = ANY(:ids)
                ORDER BY channel
                """,
                {"ids": user_ids},
            )
            for cr in contact_rows:
                contacts_by_user[cr["user_id"]].append(_contact_from_row(cr))

        users: list[UserDTO] = [_user_from_row(row, contacts_by_user[row["id"]]) for row in rows]

        return users, total

    async def get_users_by_ids(self, user_ids: list[uuid.UUID]) -> list[UserDTO]:
        if not user_ids:
            return []

        rows = await self._sql.fetch_all(
            """
            SELECT id, email, name, role, time_zone, created_at, updated_at
            FROM users
            WHERE id = ANY(:ids)
            """,
            {"ids": user_ids},
        )

        found_ids = [row["id"] for row in rows]
        contacts_by_user: dict[uuid.UUID, list[UserContactDTO]] = {uid: [] for uid in found_ids}

        if found_ids:
            contact_rows = await self._sql.fetch_all(
                """
                SELECT id, user_id, channel, contact_id, created_at, updated_at
                FROM user_contacts
                WHERE user_id = ANY(:ids)
                ORDER BY channel
                """,
                {"ids": found_ids},
            )
            for cr in contact_rows:
                contacts_by_user[cr["user_id"]].append(_contact_from_row(cr))

        return [_user_from_row(row, contacts_by_user[row["id"]]) for row in rows]

    async def upsert_user_from_crm(
        self,
        email: str,
        role: str,
        time_zone: str | None,
        name: str | None = None,
        contacts: list[CreateUserContactDTO] | None = None,
    ) -> uuid.UUID:
        # COALESCE preserves existing values when CRM sends NULL. This is intentional:
        # CRM null means "not provided", not "clear this field".
        # If CRM semantics change, switch to direct assignment.
        #
        # A conflict means the CRM now exports exactly this (email, role), i.e.
        # any pending admin email change has converged on the CRM side — so
        # email_source flips back to 'crm' HERE, not when the webhook is merely
        # delivered (the CRM-sync guard stays armed until convergence).
        user_row = await self._sql.fetch_one(
            """
            INSERT INTO users (email, name, role, time_zone, email_source)
            VALUES (:email, :name, :role, :time_zone, 'crm')
            ON CONFLICT (email, role)
            DO UPDATE SET
                name = COALESCE(EXCLUDED.name, users.name),
                time_zone = COALESCE(EXCLUDED.time_zone, users.time_zone),
                email_source = 'crm',
                updated_at = now()
            RETURNING id
            """,
            {"email": email, "name": name, "role": role, "time_zone": time_zone},
        )
        contacts_for_upsert: list[CreateUserContactDTO] = [
            *(contacts or []),
            CreateUserContactDTO(channel="email", contact_id=email),
        ]
        await self._upsert_contacts(user_row["id"], contacts_for_upsert)

        logger.debug("User upserted from CRM", email=email, role=role)
        return user_row["id"]
