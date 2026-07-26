import asyncio
from pathlib import Path

import httpx
import pytest

from amulio.app import app
from amulio.cache import CandidateCache
from amulio.config import Settings
from amulio.models import AmuleFile, Candidate
from amulio.search_locks import MediaSearchLocks
from amulio.tokens import sign


@pytest.fixture
def completed_media(tmp_path: Path) -> tuple[Candidate, Settings]:
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"0123456789")
    candidate = Candidate(
        hash="b" * 32,
        name=media.name,
        size=media.stat().st_size,
        ed2k_link=f"ed2k://|file|{media.name}|{media.stat().st_size}|{'b' * 32}|/",
    )
    settings = Settings(
        install_token="i" * 24,
        token_secret="s" * 32,
        allowed_media_roots=str(tmp_path),
        AMULE_API_ADMIN_PASSWORD="test-password",
    )

    class FakeApi:
        async def shared_file(self, file_hash: str) -> AmuleFile | None:
            assert file_hash == candidate.hash
            return AmuleFile(
                hash=candidate.hash,
                name=candidate.name,
                size=candidate.size,
                path=str(tmp_path),
            )

        async def completed_download(self, file_hash: str) -> AmuleFile | None:
            raise AssertionError("a shared completed file must not fall back to downloads")

    app.state.settings = settings
    app.state.amule_api = FakeApi()
    return candidate, settings


def _token(candidate: Candidate, settings: Settings) -> str:
    return sign(
        {"candidate": candidate.model_dump()},
        secret=settings.token_secret.get_secret_value(),
        ttl_seconds=60,
    )


@pytest.mark.asyncio
async def test_file_streaming_supports_head_and_byte_ranges(completed_media):
    candidate, settings = completed_media
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        full = await client.get(f"/file/{_token(candidate, settings)}")
        head = await client.head(f"/file/{_token(candidate, settings)}")
        single_range = await client.get(
            f"/file/{_token(candidate, settings)}", headers={"Range": "bytes=2-5"}
        )
        suffix_range = await client.get(
            f"/file/{_token(candidate, settings)}", headers={"Range": "bytes=-3"}
        )

    assert full.status_code == 200
    assert full.content == b"0123456789"
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == "10"
    assert single_range.status_code == 206
    assert single_range.headers["content-range"] == "bytes 2-5/10"
    assert single_range.content == b"2345"
    assert suffix_range.status_code == 206
    assert suffix_range.headers["content-range"] == "bytes 7-9/10"
    assert suffix_range.content == b"789"


@pytest.mark.asyncio
async def test_file_streaming_rejects_invalid_byte_ranges(completed_media):
    candidate, settings = completed_media
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/file/{_token(candidate, settings)}", headers={"Range": "bytes=10-12"}
        )

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"


@pytest.mark.asyncio
async def test_playback_seeking_switches_from_status_video_to_completed_file(
    completed_media, tmp_path
):
    candidate, settings = completed_media

    class FakeApi:
        completed = False

        async def shared_file(self, file_hash: str) -> AmuleFile | None:
            assert file_hash == candidate.hash
            if not self.completed:
                return None
            return AmuleFile(
                hash=candidate.hash,
                name=candidate.name,
                size=candidate.size,
                path=str(tmp_path),
            )

        async def download(self, file_hash: str) -> AmuleFile:
            assert file_hash == candidate.hash
            return AmuleFile(
                hash=candidate.hash,
                name=candidate.name,
                size=candidate.size,
                path="[PartFile]",
                status="completed" if self.completed else "downloading",
            )

        async def add_download(self, ed2k_link: str) -> None:
            raise AssertionError("an existing aMule download must not be enqueued again")

    cache = CandidateCache(str(tmp_path / "cache.sqlite3"))
    app.state.settings = settings
    app.state.amule_api = FakeApi()
    app.state.cache = cache
    app.state.download_locks = MediaSearchLocks()
    token = _token(candidate, settings)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=True
        ) as client:
            before_completion = await client.get(f"/play/{token}", headers={"Range": "bytes=2-5"})
            app.state.amule_api.completed = True
            after_completion = await client.get(f"/play/{token}", headers={"Range": "bytes=2-5"})
    finally:
        cache.close()

    assert before_completion.status_code == 206
    assert before_completion.headers["content-type"] == "video/mp4"
    assert before_completion.headers["cache-control"] == "no-store"
    assert before_completion.content != b"2345"
    assert after_completion.status_code == 206
    assert after_completion.headers["content-range"] == "bytes 2-5/10"
    assert after_completion.content == b"2345"


@pytest.mark.asyncio
async def test_completed_file_serves_simultaneous_clients(completed_media):
    candidate, settings = completed_media
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            *(
                client.get(f"/file/{_token(candidate, settings)}", headers={"Range": "bytes=2-5"})
                for _ in range(4)
            )
        )

    assert [response.status_code for response in responses] == [206] * 4
    assert [response.content for response in responses] == [b"2345"] * 4


@pytest.mark.asyncio
async def test_cancelling_one_playback_request_does_not_break_the_next(completed_media):
    candidate, settings = completed_media
    entered = asyncio.Event()
    release = asyncio.Event()

    class FakeApi:
        block = True

        async def shared_file(self, file_hash: str) -> AmuleFile:
            assert file_hash == candidate.hash
            if self.block:
                entered.set()
                await release.wait()
            return AmuleFile(
                hash=candidate.hash,
                name=candidate.name,
                size=candidate.size,
                path=str(Path(settings.media_roots[0])),
            )

        async def completed_download(self, file_hash: str) -> AmuleFile | None:
            return None

    app.state.settings = settings
    app.state.amule_api = FakeApi()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        cancelled = asyncio.create_task(client.get(f"/file/{_token(candidate, settings)}"))
        await entered.wait()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled

        app.state.amule_api.block = False
        release.set()
        response = await client.get(f"/file/{_token(candidate, settings)}")

    assert response.status_code == 200
    assert response.content == b"0123456789"


@pytest.mark.asyncio
async def test_disappearing_completed_file_returns_not_found(completed_media):
    candidate, settings = completed_media
    media_path = Path(settings.media_roots[0]) / candidate.name

    class FakeApi:
        async def shared_file(self, file_hash: str) -> AmuleFile:
            assert file_hash == candidate.hash
            media_path.unlink()
            return AmuleFile(
                hash=candidate.hash,
                name=candidate.name,
                size=candidate.size,
                path=str(media_path.parent),
            )

        async def completed_download(self, file_hash: str) -> AmuleFile | None:
            return None

    app.state.settings = settings
    app.state.amule_api = FakeApi()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/file/{_token(candidate, settings)}")

    assert response.status_code == 404
