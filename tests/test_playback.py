import asyncio
from types import SimpleNamespace

from fastapi import Request

from amulio.app import _download_details, _stream_object, app, play
from amulio.cache import CandidateCache, FileState
from amulio.config import Settings
from amulio.models import Candidate
from amulio.profiles import ProfilePreferences
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
    assert "4 known sources" in details


def test_remote_streams_make_download_intent_and_progress_explicit():
    settings = Settings(
        install_token="i" * 24,
        token_secret="s" * 32,
        AMULE_API_ADMIN_PASSWORD="test-password",
    )
    app.state.settings = settings
    request = type("Request", (), {"app": app})()

    new_stream = _stream_object(_candidate(), request)
    downloading_stream = _stream_object(
        _candidate(),
        request,
        file_state=FileState(
            state="downloading",
            status="downloading",
            percent=1.0,
            speed_bps=None,
            sources_total=2,
            updated_at=0,
        ),
    )

    assert new_stream["name"] == "🧲 Download with aMulio · video"
    assert "Download with aMulio" not in new_stream["description"]
    assert "💾 2.00 GB" in new_stream["description"]
    assert downloading_stream["name"] == "⬇️ Downloading with aMulio · video"
    assert "1.0%" in downloading_stream["description"]
    assert "2 known sources" in downloading_stream["description"]


def test_stream_display_preferences_hide_optional_file_facts():
    settings = Settings(
        install_token="i" * 24,
        token_secret="s" * 32,
        AMULE_API_ADMIN_PASSWORD="test-password",
    )
    app.state.settings = settings
    request = type("Request", (), {"app": app})()
    candidate = _candidate().model_copy(
        update={
            "quality": "1080p",
            "sources_total": 12,
            "language": "es",
            "codec": "HEVC",
            "hdr": True,
            "release_group": "Example",
        }
    )

    stream = _stream_object(
        candidate,
        request,
        preferences=ProfilePreferences(
            show_stream_size=False,
            show_stream_sources=False,
            show_stream_language=False,
            show_stream_technical_details=False,
        ),
    )

    assert stream["name"] == "🧲 Download with aMulio · 1080p"
    assert stream["description"] == candidate.name


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
