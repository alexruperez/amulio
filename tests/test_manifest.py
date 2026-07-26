from fastapi.testclient import TestClient

from amulio.app import app
from amulio.config import get_settings


def test_private_manifest_requires_the_installation_token(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        manifest = client.get("/" + "i" * 24 + "/manifest.json")
        rejected = client.get("/wrong/manifest.json")

    assert manifest.status_code == 200
    assert manifest.json()["behaviorHints"]["p2p"] is True
    assert manifest.json()["logo"].endswith("/assets/amule-logo.png")
    assert "configurable" not in manifest.json()["behaviorHints"]
    assert "configurationRequired" not in manifest.json()["behaviorHints"]
    assert rejected.status_code == 404
    get_settings.cache_clear()


def test_stremio_tokenized_configuration_url_requires_the_installation_token(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        configured = client.get("/" + "i" * 24 + "/configure")
        rejected = client.get("/wrong/configure")

    assert configured.status_code == 200
    assert '<html lang="en">' in configured.text
    assert "Install in Stremio" in configured.text
    assert "Copy manifest URL" in configured.text
    assert rejected.status_code == 404
    get_settings.cache_clear()


def test_configuration_page_serves_the_amule_logo(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        logo = client.get("/assets/amule-logo.png")

    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    get_settings.cache_clear()
