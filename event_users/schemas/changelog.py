import uuid
from datetime import datetime

from pydantic import BaseModel

from event_users.dto.changelog import EmailChangelogEntryDTO


class EmailChangelogEntryResponse(BaseModel):
    id: uuid.UUID
    old_email: str
    new_email: str
    changed_by: str
    changed_at: datetime

    @classmethod
    def from_dto(cls, dto: EmailChangelogEntryDTO) -> EmailChangelogEntryResponse:
        return cls(
            id=dto.id,
            old_email=dto.old_email,
            new_email=dto.new_email,
            changed_by=dto.changed_by,
            changed_at=dto.changed_at,
        )


class EmailChangelogResponse(BaseModel):
    items: list[EmailChangelogEntryResponse]
    total: int
