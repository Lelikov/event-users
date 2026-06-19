import uuid
from typing import Protocol

from event_users.dto.changelog import EmailChangelogEntryDTO


class IEmailChangelogDBAdapter(Protocol):
    async def get_changelog(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[EmailChangelogEntryDTO], int]: ...

    async def add_entry(
        self,
        *,
        user_id: uuid.UUID,
        old_email: str,
        new_email: str,
        changed_by: str,
        message_id: str | None = None,
    ) -> bool: ...
