import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EmailChangelogEntryDTO:
    id: uuid.UUID
    old_email: str
    new_email: str
    changed_by: str
    changed_at: datetime
