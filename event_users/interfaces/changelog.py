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
    ) -> None: ...

    async def is_email_changed_by_admin(self, email: str, role: str) -> bool: ...

    async def add_webhook_outbox(
        self,
        *,
        event_type: str,
        payload: dict,
    ) -> None: ...
