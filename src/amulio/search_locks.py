import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class _LockEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class MediaSearchLocks:
    """Serialise discovery work for a media key without retaining old keys."""

    def __init__(self) -> None:
        self._entries: dict[str, _LockEntry] = {}
        self._entries_lock = asyncio.Lock()

    @property
    def active_keys(self) -> int:
        return len(self._entries)

    @asynccontextmanager
    async def acquire(self, media_key: str) -> AsyncIterator[None]:
        async with self._entries_lock:
            entry = self._entries.setdefault(media_key, _LockEntry())
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._entries_lock:
                entry.users -= 1
                if entry.users == 0 and self._entries.get(media_key) is entry:
                    del self._entries[media_key]
