import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from event_users.dto.users import CreateUserDTO, ListUsersQueryDTO, UpdateUserDTO, UserDTO
from event_users.interfaces.changelog import IEmailChangelogDBAdapter
from event_users.interfaces.users import IUsersDBAdapter


class UsersController:
    def __init__(self, db_adapter: IUsersDBAdapter, changelog_adapter: IEmailChangelogDBAdapter) -> None:
        self._db = db_adapter
        self._changelog = changelog_adapter

    @staticmethod
    def _validate_timezone(time_zone: str | None) -> None:
        if time_zone is None:
            return
        try:
            ZoneInfo(time_zone)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"Invalid time_zone: {time_zone!r}") from e

    async def create_user(self, dto: CreateUserDTO) -> UserDTO:
        self._validate_timezone(dto.time_zone)
        return await self._db.create_user(dto)

    async def update_user(
        self,
        user_id: uuid.UUID,
        dto: UpdateUserDTO,
        *,
        changed_by: str = "api",
    ) -> UserDTO | None:
        self._validate_timezone(dto.time_zone)
        if dto.email is None:
            return await self._db.update_user(user_id, dto)

        current = await self._db.get_user(user_id)
        if current is None:
            return None
        if current.email == dto.email:
            return await self._db.update_user(user_id, dto)

        # Email change: same semantics as the RabbitMQ consumer path —
        # email_source='admin', changelog entry, CRM webhook outbox row,
        # all inside the request transaction.
        updated = await self._db.update_user(user_id, dto, mark_email_admin=True)
        if updated is None:
            return None
        await self._changelog.add_entry(
            user_id=user_id,
            old_email=current.email,
            new_email=dto.email,
            changed_by=changed_by,
        )
        await self._changelog.add_webhook_outbox(
            event_type="user.email.changed",
            payload={
                "user_id": str(user_id),
                "old_email": current.email,
                "new_email": dto.email,
                "changed_at": datetime.now(UTC).isoformat(),
            },
        )
        return updated

    async def get_user(self, user_id: uuid.UUID) -> UserDTO | None:
        return await self._db.get_user(user_id)

    async def get_user_by_email_role(self, email: str, role: str) -> UserDTO | None:
        return await self._db.get_user_by_email_role(email=email, role=role)

    async def list_users(self, query: ListUsersQueryDTO) -> tuple[list[UserDTO], int]:
        return await self._db.list_users(query)

    async def get_users_by_ids(self, user_ids: list[uuid.UUID]) -> list[UserDTO]:
        return await self._db.get_users_by_ids(user_ids)
