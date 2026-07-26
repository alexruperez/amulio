import asyncio

from amulio.app import _discover_candidates
from amulio.cache import CandidateCache
from amulio.config import Settings
from amulio.metadata import MediaMetadata
from amulio.models import AmuleSearchResult
from amulio.search_locks import MediaSearchLocks


async def test_same_media_key_is_serialised_and_released():
    locks = MediaSearchLocks()
    active = 0
    maximum_active = 0

    async def search() -> None:
        nonlocal active, maximum_active
        async with locks.acquire("series:tt1234567:2:4"):
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(*(search() for _ in range(10)))

    assert maximum_active == 1
    assert locks.active_keys == 0


async def test_concurrent_discovery_starts_each_amule_search_once(tmp_path):
    class FakeMetadata:
        calls = 0

        async def resolve(self, media_type: str, media_id: str) -> MediaMetadata:
            self.calls += 1
            return MediaMetadata(title="Example Film", year=2026)

    class FakeApi:
        started: list[str] = []

        async def start_search(self, query: str, *, kind: str) -> str:
            self.started.append(kind)
            await asyncio.sleep(0)
            return kind

        async def search_results(self, search_id: str) -> list[AmuleSearchResult]:
            return [
                AmuleSearchResult(
                    hash="a" * 32,
                    name="Example.Film.2026.1080p.mkv",
                    size=2_000_000_000,
                    sources={"total": 10, "complete": 5},
                )
            ]

        async def stop_search(self, search_id: str, *, close: bool) -> None:
            return None

    cache = CandidateCache(str(tmp_path / "cache.sqlite3"))
    settings = Settings(
        install_token="i" * 24,
        token_secret="s" * 32,
        AMULE_API_ADMIN_PASSWORD="test-password",
        search_wait_seconds=0,
    )
    metadata = FakeMetadata()
    api = FakeApi()
    locks = MediaSearchLocks()
    try:
        results = await asyncio.gather(
            *(
                _discover_candidates(
                    media_type="movie",
                    media_id="tt1234567",
                    api=api,  # type: ignore[arg-type]
                    metadata=metadata,  # type: ignore[arg-type]
                    cache=cache,
                    settings=settings,
                    search_locks=locks,
                )
                for _ in range(10)
            )
        )
    finally:
        cache.close()

    assert api.started.count("global") == 1
    assert api.started.count("kad") == 1
    assert metadata.calls == 1
    assert all(result == results[0] for result in results)
    assert locks.active_keys == 0


async def test_different_media_keys_can_search_concurrently():
    locks = MediaSearchLocks()
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    release = asyncio.Event()

    async def search(media_key: str, entered: asyncio.Event) -> None:
        async with locks.acquire(media_key):
            entered.set()
            await release.wait()

    first = asyncio.create_task(search("movie:tt1234567", first_entered))
    second = asyncio.create_task(search("movie:tt7654321", second_entered))
    await asyncio.wait_for(asyncio.gather(first_entered.wait(), second_entered.wait()), timeout=1)
    release.set()
    await asyncio.gather(first, second)

    assert locks.active_keys == 0
