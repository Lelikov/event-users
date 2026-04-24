import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr

from event_users.dto.users import (
    CreateUserContactDTO,
    CreateUserDTO,
    ListUsersQueryDTO,
    UpdateUserDTO,
    UserContactDTO,
    UserDTO,
)


class UserContactResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    channel: str
    contact_id: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, dto: UserContactDTO) -> UserContactResponse:
        return cls(
            id=dto.id,
            user_id=dto.user_id,
            channel=dto.channel,
            contact_id=dto.contact_id,
            created_at=dto.created_at,
            updated_at=dto.updated_at,
        )


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    time_zone: str | None
    contacts: list[UserContactResponse]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dto(cls, dto: UserDTO) -> UserResponse:
        return cls(
            id=dto.id,
            email=dto.email,
            name=dto.name,
            role=dto.role,
            time_zone=dto.time_zone,
            contacts=[UserContactResponse.from_dto(c) for c in dto.contacts],
            created_at=dto.created_at,
            updated_at=dto.updated_at,
        )


class UserContactRequest(BaseModel):
    channel: str
    contact_id: str

    def to_dto(self) -> CreateUserContactDTO:
        return CreateUserContactDTO(channel=self.channel, contact_id=self.contact_id)


class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    role: Literal["client", "organizer"]
    time_zone: str = "Europe/Moscow"
    contacts: list[UserContactRequest] = []

    def to_dto(self) -> CreateUserDTO:
        return CreateUserDTO(
            email=self.email,
            name=self.name,
            role=self.role,
            time_zone=self.time_zone,
            contacts=[c.to_dto() for c in self.contacts],
        )


class UpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    name: str | None = None
    role: Literal["client", "organizer"] | None = None
    time_zone: str | None = None
    contacts: list[UserContactRequest] | None = None

    def to_dto(self) -> UpdateUserDTO:
        return UpdateUserDTO(
            email=self.email,
            name=self.name,
            role=self.role,
            time_zone=self.time_zone,
            contacts=[c.to_dto() for c in self.contacts] if self.contacts is not None else None,
        )


class GetUsersByIdsRequest(BaseModel):
    ids: list[uuid.UUID]


class GetUsersByIdsResponse(BaseModel):
    items: list[UserResponse]


class ListUsersResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class ListUsersParams(BaseModel):
    email: str | None = None
    role: Literal["client", "organizer"] | None = None
    limit: int = 50
    offset: int = 0

    def to_dto(self) -> ListUsersQueryDTO:
        return ListUsersQueryDTO(
            email=self.email,
            role=self.role,
            limit=self.limit,
            offset=self.offset,
        )
