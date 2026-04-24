"""Interface for cache invalidation notifier."""

from typing import Protocol


class ICacheNotifier(Protocol):
    async def invalidate(self) -> None: ...
