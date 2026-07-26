import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from amulio.app import _safe_media_path
from amulio.config import Settings


@pytest.fixture
def media_root(tmp_path: Path) -> tuple[Path, Settings]:
    root = tmp_path / "incoming"
    root.mkdir()
    settings = Settings(
        install_token="i" * 24,
        token_secret="s" * 32,
        allowed_media_roots=str(root),
        AMULE_API_ADMIN_PASSWORD="test-password",
    )
    return root, settings


def test_media_path_rejects_traversal_outside_allowed_root(media_root, tmp_path):
    root, settings = media_root
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"private")

    with pytest.raises(HTTPException) as error:
        _safe_media_path(str(root / ".." / outside.name), settings=settings)

    assert error.value.status_code == 403


def test_media_path_does_not_decode_encoded_traversal(media_root):
    root, settings = media_root

    with pytest.raises(HTTPException) as error:
        _safe_media_path(str(root / "%2e%2e" / "outside.mp4"), settings=settings)

    assert error.value.status_code == 404


def test_media_path_rejects_symlink_escaping_allowed_root(media_root, tmp_path):
    root, settings = media_root
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"private")
    link = root / "linked.mp4"
    link.symlink_to(outside)

    with pytest.raises(HTTPException) as error:
        _safe_media_path(str(link), settings=settings)

    assert error.value.status_code == 403


def test_media_path_rejects_non_regular_files(media_root):
    root, settings = media_root
    fifo = root / "stream.mp4"
    os.mkfifo(fifo)

    with pytest.raises(HTTPException) as error:
        _safe_media_path(str(fifo), settings=settings)

    assert error.value.status_code == 404
