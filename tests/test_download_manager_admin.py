from fastapi.testclient import TestClient

from amulio.app import app
from amulio.config import get_settings


class FakeAmuleApi:
    def __init__(self):
        self.download_items = [
            {
                "hash": "a" * 32,
                "name": "active.mkv",
                "size": 100,
                "size_done": 40,
                "status": "downloading",
            },
            {"hash": "b" * 32, "name": "finished.mkv", "size": 200, "status": "completed"},
        ]
        self.shared_items = [{"hash": "b" * 32, "name": "finished.mkv", "size": 200}]
        self.calls: list[tuple[str, list[str]]] = []

    async def downloads(self):
        return self.download_items

    async def shared_files(self):
        return self.shared_items

    async def pause_downloads(self, hashes):
        self.calls.append(("pause", hashes))
        return [{"id": value, "ok": True} for value in hashes]

    async def resume_downloads(self, hashes):
        self.calls.append(("resume", hashes))
        return [{"id": value, "ok": True} for value in hashes]

    async def cancel_downloads(self, hashes):
        self.calls.append(("cancel", hashes))
        return [{"id": value, "ok": True} for value in hashes]

    async def health(self):
        return {}

    async def close(self):
        pass


class FakeMetadata:
    async def close(self):
        pass


def configure_admin(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULIO_ADMIN_PASSWORD", "a" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    get_settings.cache_clear()


def login(client):
    response = client.post("/admin/session", json={"password": "a" * 32})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_download_manager_requires_admin_session_csrf_and_active_selections(monkeypatch):
    configure_admin(monkeypatch)
    with TestClient(app) as client:
        fake = FakeAmuleApi()
        app.state.amule_api = fake
        assert client.get("/admin/downloads").status_code == 401
        csrf = login(client)

        listing = client.get("/admin/downloads")
        assert listing.status_code == 200
        assert listing.json() == {
            "downloads": [
                {
                    "hash": "a" * 32,
                    "name": "active.mkv",
                    "size": 100,
                    "size_done": 40,
                    "speed_bps": 0,
                    "status": "downloading",
                }
            ],
            "shared": [{"hash": "b" * 32, "name": "finished.mkv", "size": 200}],
        }
        assert (
            client.patch(
                "/admin/downloads", json={"hashes": ["a" * 32], "action": "pause"}
            ).status_code
            == 403
        )
        paused = client.patch(
            "/admin/downloads",
            headers={"X-CSRF-Token": csrf},
            json={"hashes": ["A" * 32], "action": "pause"},
        )
        assert paused.status_code == 200
        assert fake.calls == [("pause", ["a" * 32])]
        # Completed, unknown, malformed and duplicate choices never reach aMule.
        assert (
            client.patch(
                "/admin/downloads",
                headers={"X-CSRF-Token": csrf},
                json={"hashes": ["b" * 32], "action": "resume"},
            ).status_code
            == 409
        )
        assert (
            client.patch(
                "/admin/downloads",
                headers={"X-CSRF-Token": csrf},
                json={"hashes": ["not-a-hash"], "action": "resume"},
            ).status_code
            == 422
        )
        assert (
            client.patch(
                "/admin/downloads",
                headers={"X-CSRF-Token": csrf},
                json={"hashes": ["a" * 32, "a" * 32], "action": "resume"},
            ).status_code
            == 422
        )

    get_settings.cache_clear()


def test_cancellation_requires_exact_spanish_count_confirmation(monkeypatch):
    configure_admin(monkeypatch)
    with TestClient(app) as client:
        fake = FakeAmuleApi()
        app.state.amule_api = fake
        csrf = login(client)
        payload = {"hashes": ["a" * 32], "confirmation": "CANCELAR 2"}
        assert (
            client.request(
                "DELETE", "/admin/downloads", headers={"X-CSRF-Token": csrf}, json=payload
            ).status_code
            == 422
        )
        payload["confirmation"] = "CANCELAR 1"
        cancelled = client.request(
            "DELETE", "/admin/downloads", headers={"X-CSRF-Token": csrf}, json=payload
        )
        assert cancelled.status_code == 200
        assert fake.calls == [("cancel", ["a" * 32])]
        # The completed item cannot be cancelled even with a valid confirmation.
        payload = {"hashes": ["b" * 32], "confirmation": "CANCELAR 1"}
        assert (
            client.request(
                "DELETE", "/admin/downloads", headers={"X-CSRF-Token": csrf}, json=payload
            ).status_code
            == 409
        )

    get_settings.cache_clear()


def test_manager_is_hidden_when_admin_password_is_unavailable(monkeypatch):
    monkeypatch.setenv("AMULIO_INSTALL_TOKEN", "i" * 24)
    monkeypatch.setenv("AMULIO_TOKEN_SECRET", "s" * 32)
    monkeypatch.setenv("AMULE_API_ADMIN_PASSWORD", "test-password")
    monkeypatch.delenv("AMULIO_ADMIN_PASSWORD", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert 'id="download-manager" hidden' in client.get("/configure").text
        assert client.get("/admin/downloads").status_code == 401
    get_settings.cache_clear()
