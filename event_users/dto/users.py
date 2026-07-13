import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UserContactDTO:
    id: uuid.UUID
    user_id: uuid.UUID
    channel: str
    contact_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UserDTO:
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    time_zone: str | None
    contacts: list[UserContactDTO]
    created_at: datetime
    updated_at: datetime
    locale: str | None = None


@dataclass(frozen=True)
class CreateUserContactDTO:
    channel: str
    contact_id: str


@dataclass(frozen=True)
class CreateUserDTO:
    email: str
    name: str | None
    role: str
    time_zone: str | None
    contacts: list[CreateUserContactDTO]


@dataclass(frozen=True)
class UpdateUserDTO:
    email: str | None
    name: str | None
    role: str | None
    time_zone: str | None
    contacts: list[CreateUserContactDTO] | None


@dataclass(frozen=True)
class ListUsersQueryDTO:
    email: str | None
    role: str | None
    limit: int
    offset: int
