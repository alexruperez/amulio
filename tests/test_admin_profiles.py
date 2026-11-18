from fastapi.testclient import TestClient

from amulio.app import app
from amulio.config import get_settings


def _configure_admin(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULIO_ADMIN_PASSWORD", "a" * 32)
    monkeypatch.delenv("AMULIO_ADMIN_BOOTSTRAP_TOKEN", raising=False)
    monkeypatch.delenv("AMULIO_ADMIN_BOOTSTRAP_TOKEN_FILE", raising=False)
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


def test_bootstrap_establishes_a_csrf_protected_session_only_when_configured(monkeypatch):
    _configure_admin(monkeypatch)
    bootstrap_token = "b" * 32
    monkeypatch.setenv("AMULIO_ADMIN_BOOTSTRAP_TOKEN", bootstrap_token)
    get_settings.cache_clear()

    with TestClient(app) as client:
        configure_page = client.get("/configure")
        assert '<div id="manager-bootstrap">' not in configure_page.text
        assert bootstrap_token not in configure_page.text

        wrong = client.post("/admin/bootstrap", json={"token": "x" * 32})
        assert wrong.status_code == 401

        bootstrap = client.post("/admin/bootstrap", json={"token": bootstrap_token})
        assert bootstrap.status_code == 200
        assert bootstrap_token not in bootstrap.text
        assert "HttpOnly" in bootstrap.headers["set-cookie"]
        csrf_token = bootstrap.json()["csrf_token"]

        created = client.post(
            "/admin/profiles",
            headers={"X-CSRF-Token": csrf_token},
            json={"ui_language": "en", "search_languages": ["en"], "result_limit": 10},
        )
        assert created.status_code == 201
        manifest = client.get("/" + "i" * 24 + "/manifest.json")
        assert bootstrap_token not in manifest.text

    get_settings.cache_clear()


def test_bootstrap_is_disabled_without_its_secret_or_admin_password(monkeypatch):
    _configure_admin(monkeypatch)
    with TestClient(app) as client:
        assert '<div id="manager-bootstrap">' not in client.get("/configure").text
        assert client.post("/admin/bootstrap", json={"token": "b" * 32}).status_code == 404

    monkeypatch.setenv("AMULIO_ADMIN_BOOTSTRAP_TOKEN", "b" * 32)
    monkeypatch.delenv("AMULIO_ADMIN_PASSWORD", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.post("/admin/bootstrap", json={"token": "b" * 32}).status_code == 404

    get_settings.cache_clear()


def test_admin_bootstrap_token_can_be_loaded_from_a_private_file(monkeypatch, tmp_path):
    _configure_admin(monkeypatch)
    token_file = tmp_path / "amulio_admin_bootstrap_token"
    token_file.write_text("b" * 32)
    monkeypatch.setenv("AMULIO_ADMIN_BOOTSTRAP_TOKEN_FILE", str(token_file))
    get_settings.cache_clear()

    with TestClient(app) as client:
        assert client.post("/admin/bootstrap", json={"token": "b" * 32}).status_code == 200

    get_settings.cache_clear()


def test_bootstrap_rate_limit_is_separate_from_admin_login(monkeypatch):
    _configure_admin(monkeypatch)
    monkeypatch.setenv("AMULIO_ADMIN_BOOTSTRAP_TOKEN", "b" * 32)
    monkeypatch.setenv("AMULIO_ADMIN_BOOTSTRAP_RATE_LIMIT", "1")
    get_settings.cache_clear()

    with TestClient(app) as client:
        assert client.post("/admin/bootstrap", json={"token": "x" * 32}).status_code == 401
        assert client.post("/admin/bootstrap", json={"token": "b" * 32}).status_code == 429

    get_settings.cache_clear()
