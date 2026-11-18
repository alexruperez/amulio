from fastapi.testclient import TestClient

from amulio.app import app
from amulio.config import get_settings


def _configure(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("AMULIO_TRUSTED_INGRESS_PROXY_SOURCES", "172.30.32.2/32")
    monkeypatch.delenv("AMULIO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("AMULIO_ADMIN_PASSWORD_FILE", raising=False)
    get_settings.cache_clear()


def test_ingress_sso_requires_a_trusted_proxy_and_identity_header(monkeypatch):
    _configure(monkeypatch)
    ingress_headers = {
        "X-Remote-User-ID": "owner",
        "X-Ingress-Path": "/api/hassio_ingress/abc123",
    }
    with TestClient(app, client=("172.30.32.2", 4567)) as trusted:
        accepted = trusted.post("/admin/ingress-session", headers=ingress_headers)
        assert accepted.status_code == 200
        assert "HttpOnly" in accepted.headers["set-cookie"]
        assert "SameSite=strict" in accepted.headers["set-cookie"]
        assert "Path=/api/hassio_ingress/abc123/admin" in accepted.headers["set-cookie"]
        session_cookie = accepted.cookies.get("amulio_admin")
        assert session_cookie is not None
        deleted = trusted.request(
            "DELETE",
            "/admin/session",
            headers={
                "Cookie": f"amulio_admin={session_cookie}",
                "X-CSRF-Token": accepted.json()["csrf_token"],
                **ingress_headers,
            },
        )
        assert "Path=/api/hassio_ingress/abc123/admin" in deleted.headers["set-cookie"]
        assert (
            trusted.post(
                "/admin/ingress-session",
                headers={"X-Remote-User-ID": "owner", "X-Ingress-Path": "https://invalid"},
            ).status_code
            == 401
        )

    with TestClient(app, client=("198.51.100.8", 4567)) as untrusted:
        assert (
            untrusted.post(
                "/admin/ingress-session",
                headers={
                    "X-Remote-User-ID": "spoofed",
                    "X-Ingress-Path": "/api/hassio_ingress/spoofed",
                },
            ).status_code
            == 401
        )

    with TestClient(app, client=("172.30.32.2", 4567)) as missing_header:
        assert missing_header.post("/admin/ingress-session").status_code == 401
    get_settings.cache_clear()


def test_generic_admin_session_keeps_the_admin_cookie_path(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("AMULIO_ADMIN_PASSWORD", "a" * 32)
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.post("/admin/session", json={"password": "a" * 32})

    assert response.status_code == 200
    assert "Path=/admin" in response.headers["set-cookie"]
    get_settings.cache_clear()


def test_ingress_configuration_hides_generic_credentials(monkeypatch):
    class FakeAmuleApi:
        async def health(self):
            return {}

        async def close(self):
            return None

    _configure(monkeypatch)
    monkeypatch.setenv("AMULIO_ADMIN_PASSWORD", "a" * 32)
    get_settings.cache_clear()
    ingress_headers = {
        "X-Remote-User-ID": "owner",
        "X-Ingress-Path": "/api/hassio_ingress/abc123",
    }
    with TestClient(app, client=("172.30.32.2", 4567)) as trusted:
        app.state.amule_api = FakeAmuleApi()
        ingress = trusted.get("/configure", headers=ingress_headers)
        readiness = trusted.get("/configure/status", headers=ingress_headers)
    with TestClient(app, client=("198.51.100.8", 4567)) as direct:
        public = direct.get(
            "/configure",
            headers={
                "X-Remote-User-ID": "spoofed",
                "X-Ingress-Path": "/api/hassio_ingress/spoofed",
            },
        )
        rejected_status = direct.get("/configure/status", headers=ingress_headers)

    assert "Open download manager" in ingress.text
    assert 'data-status-url="configure/status"' in ingress.text
    assert 'const managerApiBase = ingressSso ? "admin" : "../admin";' in ingress.text
    assert '`${managerApiBase}/${ingressSso ? "ingress-session" : "session"}`' in ingress.text
    assert "`${managerApiBase}/downloads`" in ingress.text
    assert readiness.status_code == 200
    assert 'id="manager-password"' not in ingress.text
    assert 'id="manager-bootstrap"' not in ingress.text
    assert '<details class="profile-settings" hidden>' in ingress.text
    assert "Open download manager" not in public.text
    assert f'data-status-url="http://127.0.0.1:8000/{"i" * 24}/configure/status"' in public.text
    assert rejected_status.status_code == 404

    with TestClient(app, client=("198.51.100.8", 4567)) as direct_with_password:
        tokenized = direct_with_password.get(f"/{'i' * 24}/configure")
        public_with_password = direct_with_password.get("/configure")
    for response in (tokenized, public_with_password):
        assert 'id="download-manager"' not in response.text
        assert 'id="manager-password"' not in response.text
        assert 'id="manager-bootstrap"' not in response.text
        assert "managerApiBase" not in response.text
        assert "managerCancelConfirm" not in response.text
    get_settings.cache_clear()
