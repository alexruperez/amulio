from fastapi.testclient import TestClient

from amulio.app import AMULE_LOGO_VERSION, app
from amulio.config import get_settings
from amulio.models import Candidate
from amulio.profiles import ProfilePreferences


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
    assert manifest.json()["logo"].endswith(f"/assets/amule-logo.png?v={AMULE_LOGO_VERSION}")
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
    assert 'id="action-feedback"' in configured.text
    assert "Opening Stremio…" in configured.text
    assert "Basic" in configured.text
    assert "Search" in configured.text
    assert "Advanced" in configured.text
    assert rejected.status_code == 404
    get_settings.cache_clear()


def test_configuration_page_serves_the_amule_logo(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        logo = client.get(f"/assets/amule-logo.png?v={AMULE_LOGO_VERSION}")

    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    get_settings.cache_clear()


def test_configuration_page_can_be_rendered_in_spanish(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        configured = client.get("/configure?lang=es")

    assert '<html lang="es">' in configured.text
    assert "Instalar en Stremio" in configured.text
    assert "Estado de la instancia" in configured.text
    assert 'id="profile-form"' in configured.text
    assert "Ajustes del perfil" in configured.text
    assert "Básico" in configured.text
    assert "Búsqueda" in configured.text
    assert "Avanzado" in configured.text
    assert "Abriendo Stremio…" in configured.text
    assert "eD2K está desconectado" in configured.text
    get_settings.cache_clear()


def test_configuration_readiness_is_private_and_exposes_only_safe_connection_states(
    monkeypatch, tmp_path
):
    class FakeAmuleApi:
        async def health(self):
            return {
                "ed2k": {"state": "connected"},
                "kad": {"state": "connecting"},
                "password": "must-not-be-returned",
            }

        async def close(self):
            return None

    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("AMULIO_ALLOWED_MEDIA_ROOTS", str(tmp_path))
    get_settings.cache_clear()

    with TestClient(app) as client:
        app.state.amule_api = FakeAmuleApi()
        readiness = client.get("/" + "i" * 24 + "/configure/status")
        rejected = client.get("/wrong/configure/status")

    assert readiness.status_code == 200
    assert readiness.headers["cache-control"] == "no-store"
    assert readiness.json() == {
        "amuleapi": "connected",
        "ed2k": "connected",
        "kad": "connecting",
        "incoming_storage": "ready",
        "public_url": "configured",
    }
    assert "password" not in readiness.text
    assert rejected.status_code == 404
    get_settings.cache_clear()


def test_profile_manifest_and_streams_use_revocable_profile_preferences(monkeypatch):
    observed: dict[str, object] = {}

    async def candidates_with_profile(**kwargs):
        observed.update(kwargs)
        return [
            Candidate(
                hash="a" * 32,
                name="Example.Film.2026.1080p.ESP.mkv",
                size=2_000_000_000,
                sources_total=4,
                sources_complete=2,
                ed2k_link="ed2k://|file|Example.Film.2026.1080p.ESP.mkv|2000000000|"
                + "a" * 32
                + "|/",
                quality="1080p",
                language="es",
            )
        ]

    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    monkeypatch.setattr("amulio.app._discover_candidates", candidates_with_profile)
    get_settings.cache_clear()

    with TestClient(app) as client:
        profile = app.state.profile_store.create(
            ProfilePreferences(ui_language="es", search_languages=("es",), result_limit=3)
        )
        manifest = client.get("/" + "i" * 24 + f"/profile/{profile.id}/manifest.json")
        stream = client.get("/" + "i" * 24 + f"/profile/{profile.id}/stream/movie/tt1234567.json")
        app.state.profile_store.revoke(profile.id)
        revoked = client.get("/" + "i" * 24 + f"/profile/{profile.id}/manifest.json")

    assert manifest.status_code == 200
    assert manifest.json()["id"].endswith(profile.id)
    assert manifest.json()["description"].startswith("Busca contenido")
    assert stream.status_code == 200
    assert stream.json()["streams"][0]["name"] == "🧲 aMulio · Descargar con aMule · 1080p"
    assert observed["preferences"] == profile.preferences
    assert observed["cache_scope"] == f"profile:{profile.id}"
    assert revoked.status_code == 404
    get_settings.cache_clear()
