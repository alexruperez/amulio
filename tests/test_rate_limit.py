import pytest
from fastapi.testclient import TestClient

from amulio.app import app
from amulio.config import get_settings
from amulio.rate_limit import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_is_scoped_to_each_client_key():
    limiter = SlidingWindowRateLimiter()

    assert await limiter.allow("stream:token:127.0.0.1", limit=1, window_seconds=60)
    assert not await limiter.allow("stream:token:127.0.0.1", limit=1, window_seconds=60)
    assert await limiter.allow("stream:token:127.0.0.2", limit=1, window_seconds=60)


def test_manifest_route_rate_limits_a_token_and_client(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULIO_MANIFEST_RATE_LIMIT", "1")
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        first = client.get("/" + "i" * 24 + "/manifest.json")
        second = client.get("/" + "i" * 24 + "/manifest.json")

    assert first.status_code == 200
    assert second.status_code == 429
    get_settings.cache_clear()
