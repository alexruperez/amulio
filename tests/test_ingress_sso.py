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
    with TestClient(app, client=("172.30.32.2", 4567)) as trusted:
        accepted = trusted.post("/admin/ingress-session", headers={"X-Remote-User-ID": "owner"})
        assert accepted.status_code == 200
        assert "HttpOnly" in accepted.headers["set-cookie"]
        assert "SameSite=strict" in accepted.headers["set-cookie"]
        assert trusted.post("/admin/profiles").status_code == 403

    with TestClient(app, client=("198.51.100.8", 4567)) as untrusted:
        assert untrusted.post(
            "/admin/ingress-session", headers={"X-Remote-User-ID": "spoofed"}
        ).status_code == 401

    with TestClient(app, client=("172.30.32.2", 4567)) as missing_header:
        assert missing_header.post("/admin/ingress-session").status_code == 401
    get_settings.cache_clear()


def test_ingress_configuration_hides_generic_credentials(monkeypatch):
    _configure(monkeypatch)
    with TestClient(app, client=("172.30.32.2", 4567)) as trusted:
        ingress = trusted.get("/configure", headers={"X-Remote-User-ID": "owner"})
    with TestClient(app, client=("198.51.100.8", 4567)) as direct:
        public = direct.get("/configure", headers={"X-Remote-User-ID": "spoofed"})

    assert "Open download manager" in ingress.text
    assert 'id="manager-password"' not in ingress.text
    assert 'id="manager-bootstrap"' not in ingress.text
    assert '<details class="profile-settings" hidden>' in ingress.text
    assert "Open download manager" not in public.text
    get_settings.cache_clear()
