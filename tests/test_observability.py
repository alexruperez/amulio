from fastapi.testclient import TestClient

from amulio.app import app
from amulio.config import get_settings


def test_metrics_are_disabled_without_a_metrics_token(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 404
    get_settings.cache_clear()


def test_metrics_require_a_bearer_token_and_expose_prometheus_output(monkeypatch):
    token = "m" * 24
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULIO_METRICS_TOKEN", token)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        denied = client.get("/metrics")
        metrics = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})

    assert denied.status_code == 404
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "amulio_http_requests_total" in metrics.text
    assert 'route="/metrics"' in metrics.text
    get_settings.cache_clear()
