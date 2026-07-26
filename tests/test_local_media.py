from pathlib import Path

from amulio.config import Settings
from amulio.local_media import discover_local_media
from amulio.metadata import MediaMetadata


def test_completed_local_video_is_discovered_even_when_small(tmp_path: Path):
    video = tmp_path / "Avatar.2009.720p.H264.mp4"
    video.write_bytes(b"demo")
    settings = Settings(
        install_token="i" * 24,
        token_secret="s" * 32,
        allowed_media_roots=str(tmp_path),
        AMULE_API_ADMIN_PASSWORD="test-password",
    )

    candidates = discover_local_media(MediaMetadata(title="Avatar", year=2009), settings)

    assert len(candidates) == 1
    assert candidates[0].name == video.name
    assert candidates[0].size == 4
    assert candidates[0].local_path == str(video)
