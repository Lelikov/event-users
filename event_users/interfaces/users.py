import uuid
from typing import Protocol

from event_users.dto.users import (
    CreateUserContactDTO,
    CreateUserDTO,
    ListUsersQueryDTO,
    UpdateUserDTO,
    UserDTO,
)


class IUsersDBAdapter(Protocol):
    async def create_user(self, dto: CreateUserDTO) -> UserDTO: ...

    async def update_user(self, user_id: uuid.UUID, dto: UpdateUserDTO) -> UserDTO | None: ...

    async def get_user(self, user_id: uuid.UUID) -> UserDTO | None: ...

    async def get_user_by_email_role(self, email: str, role: str) -> UserDTO | None: ...

    async def list_users(self, query: ListUsersQueryDTO) -> tuple[list[UserDTO], int]: ...

    async def get_users_by_ids(self, user_ids: list[uuid.UUID]) -> list[UserDTO]: ...

    async def upsert_user_from_crm(
        self,
        email: str,
        role: str,
        time_zone: str | None,
        name: str | None = None,
        contacts: list[CreateUserContactDTO] | None = None,
    ) -> None: ...


class IUsersController(Protocol):
    async def create_user(self, dto: CreateUserDTO) -> UserDTO: ...

    async def update_user(self, user_id: uuid.UUID, dto: UpdateUserDTO) -> UserDTO | None: ...

    async def get_user(self, user_id: uuid.UUID) -> UserDTO | None: ...

    async def get_user_by_email_role(self, email: str, role: str) -> UserDTO | None: ...

    async def list_users(self, query: ListUsersQueryDTO) -> tuple[list[UserDTO], int]: ...

    async def get_users_by_ids(self, user_ids: list[uuid.UUID]) -> list[UserDTO]: ...
