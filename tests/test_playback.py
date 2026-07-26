import asyncio
from types import SimpleNamespace

from fastapi import Request

from amulio.app import _download_details, app, play
from amulio.cache import CandidateCache, FileState
from amulio.config import Settings
from amulio.models import Candidate
from amulio.search_locks import MediaSearchLocks
from amulio.tokens import sign


def _candidate() -> Candidate:
    return Candidate(
        hash="a" * 32,
        name="Example.Film.2026.1080p.mkv",
        size=2_000_000_000,
        ed2k_link="ed2k://|file|Example.Film.2026.1080p.mkv|2000000000|" + "a" * 32 + "|/",
    )


def test_download_details_include_live_metrics():
    details = _download_details(
        FileState(
            state="downloading",
            status="downloading",
            percent=50.5,
            speed_bps=2_500_000,
            sources_total=4,
            updated_at=0,
        )
    )

    assert "50.5%" in details
    assert "2.50 MB/s" in details
    assert "4 fuentes activas" in details


async def test_play_enqueues_a_new_download_once_and_returns_a_status_video(tmp_path):
    candidate = _candidate()

    class FakeApi:
        downloads: set[str] = set()
        enqueued = 0

        async def shared_file(self, file_hash: str):
            return None

        async def download(self, file_hash: str):
            await asyncio.sleep(0)
            if file_hash not in self.downloads:
                return None
            return SimpleNamespace(status="downloading")

        async def add_download(self, ed2k_link: str) -> None:
            self.enqueued += 1
            self.downloads.add(candidate.hash)

    settings = Settings(
        install_token="i" * 24,
        token_secret="s" * 32,
        AMULE_API_ADMIN_PASSWORD="test-password",
    )
    app.state.settings = settings
    app.state.download_locks = MediaSearchLocks()
    request = Request({"type": "http", "app": app, "method": "GET", "headers": []})
    token = sign(
        {"candidate": candidate.model_dump()},
        secret=settings.token_secret.get_secret_value(),
        ttl_seconds=60,
    )
    cache = CandidateCache(str(tmp_path / "cache.sqlite3"))
    api = FakeApi()
    try:
        responses = await asyncio.gather(*(play(token, request, api, cache) for _ in range(2)))
    finally:
        cache.close()

    assert api.enqueued == 1
    assert responses[0].media_type == "video/mp4"
    assert responses[1].media_type == "video/mp4"
