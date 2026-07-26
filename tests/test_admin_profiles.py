from fastapi.testclient import TestClient

from amulio.app import app
from amulio.config import get_settings


def _configure_admin(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULIO_ADMIN_PASSWORD", "a" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()


def test_profile_administration_requires_a_separate_csrf_protected_session(monkeypatch):
    _configure_admin(monkeypatch)

    with TestClient(app) as client:
        assert client.post("/admin/profiles").status_code == 401
        assert client.post("/admin/session", json={"password": "wrong"}).status_code == 401

        login = client.post("/admin/session", json={"password": "a" * 32})
        assert login.status_code == 200
        csrf_token = login.json()["csrf_token"]
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "SameSite=strict" in login.headers["set-cookie"]

        assert client.post("/admin/profiles").status_code == 403
        created = client.post(
            "/admin/profiles",
            headers={"X-CSRF-Token": csrf_token},
            json={"ui_language": "es", "search_languages": ["es", "en"], "result_limit": 15},
        )
        assert created.status_code == 201
        profile = created.json()

        fetched = client.get(f"/admin/profiles/{profile['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["preferences"]["ui_language"] == "es"

        rotated = client.post(
            f"/admin/profiles/{profile['id']}/rotate", headers={"X-CSRF-Token": csrf_token}
        )
        assert rotated.status_code == 200
        assert rotated.json()["id"] != profile["id"]
        assert client.get(f"/admin/profiles/{profile['id']}").status_code == 404

        logout = client.delete("/admin/session", headers={"X-CSRF-Token": csrf_token})
        assert logout.status_code == 204
        assert client.get(f"/admin/profiles/{rotated.json()['id']}").status_code == 401

    get_settings.cache_clear()


def test_admin_api_is_not_exposed_until_an_admin_password_is_configured(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    monkeypatch.delenv("AMULIO_ADMIN_PASSWORD", raising=False)
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.post("/admin/session", json={"password": "a" * 32})

    assert response.status_code == 404
    get_settings.cache_clear()


def test_admin_password_can_be_loaded_from_a_private_file(monkeypatch, tmp_path):
    password_file = tmp_path / "amulio_admin_password"
    password_file.write_text("a" * 32)
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULIO_ADMIN_PASSWORD_FILE", str(password_file))
    monkeypatch.delenv("AMULIO_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()

    with TestClient(app) as client:
        assert client.post("/admin/session", json={"password": "a" * 32}).status_code == 200

    get_settings.cache_clear()
