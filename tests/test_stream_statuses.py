from fastapi.testclient import TestClient

from amulio.amule_api import AmuleApiError
from amulio.app import app
from amulio.config import get_settings


def _configure(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()


def test_empty_search_results_return_an_explanatory_stremio_stream(monkeypatch):
    async def no_candidates(**_kwargs):
        return []

    _configure(monkeypatch)
    monkeypatch.setattr("amulio.app._discover_candidates", no_candidates)

    with TestClient(app) as client:
        response = client.get("/" + "i" * 24 + "/stream/movie/tt1234567.json")
        video = client.get("/assets/no-results.mp4")

    stream = response.json()["streams"][0]
    assert response.status_code == 200
    assert stream["name"] == "ℹ️ aMulio · No matching files found"
    assert stream["url"].endswith("/assets/no-results.mp4")
    assert stream["behaviorHints"]["notWebReady"] is False
    assert video.headers["content-type"] == "video/mp4"
    get_settings.cache_clear()


def test_amule_errors_return_an_explanatory_stremio_stream(monkeypatch):
    async def unavailable(**_kwargs):
        raise AmuleApiError("connection refused")

    _configure(monkeypatch)
    monkeypatch.setattr("amulio.app._discover_candidates", unavailable)

    with TestClient(app) as client:
        response = client.get("/" + "i" * 24 + "/stream/movie/tt1234567.json")

    stream = response.json()["streams"][0]
    assert response.status_code == 200
    assert stream["name"] == "ℹ️ aMulio · aMule is unavailable"
    assert stream["url"].endswith("/assets/amule-unavailable.mp4")
    get_settings.cache_clear()
