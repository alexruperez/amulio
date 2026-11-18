from fastapi.testclient import TestClient

from amulio.app import app
from amulio.config import get_settings
from amulio.models import AmuleFile


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
        self.shared_items = [
            {"hash": "A" * 32, "name": "active-preview.mkv", "size": 100},
            {"hash": "b" * 32, "name": "finished.mkv", "size": 200},
        ]
        self.calls: list[tuple[str, list[str]]] = []

    async def downloads(self):
        return self.download_items

    async def shared_files(self):
        return self.shared_items

    async def shared_file(self, _file_hash) -> AmuleFile | None:
        return None

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
            "shared": [],
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


def test_cancellation_requires_only_an_active_selection(monkeypatch):
    configure_admin(monkeypatch)
    with TestClient(app) as client:
        fake = FakeAmuleApi()
        app.state.amule_api = fake
        csrf = login(client)
        cancelled = client.request(
            "DELETE",
            "/admin/downloads",
            headers={"X-CSRF-Token": csrf},
            json={"hashes": ["a" * 32]},
        )
        assert cancelled.status_code == 200
        assert fake.calls == [("cancel", ["a" * 32])]
        # The completed item cannot be cancelled.
        assert (
            client.request(
                "DELETE",
                "/admin/downloads",
                headers={"X-CSRF-Token": csrf},
                json={"hashes": ["b" * 32]},
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
        assert 'id="download-manager"' not in client.get("/configure").text
        assert client.get("/admin/downloads").status_code == 401
    get_settings.cache_clear()


class StaleSharedLibraryApi(FakeAmuleApi):
    def __init__(self, media_root):
        super().__init__()
        self.download_items = []
        self.media_root = media_root
        self.file_hash = "b" * 32
        self.shared_items = [{"hash": self.file_hash, "name": "finished.mkv", "size": 200}]
        self.reloads = 0
        (media_root / "finished.mkv").write_bytes(b"x" * 200)

    async def shared_file(self, file_hash):
        if file_hash.lower() != self.file_hash:
            return None
        return AmuleFile(
            hash=self.file_hash,
            name="finished.mkv",
            size=200,
            path=str(self.media_root),
        )

    async def reload_shared_files(self):
        self.reloads += 1


def test_completed_library_delete_is_idempotent_and_hides_stale_shared_entries(
    monkeypatch, tmp_path
):
    configure_admin(monkeypatch)
    media_root = tmp_path / "incoming"
    media_root.mkdir()
    monkeypatch.setenv("AMULIO_ALLOWED_MEDIA_ROOTS", str(media_root))
    get_settings.cache_clear()
    with TestClient(app) as client:
        fake = StaleSharedLibraryApi(media_root)
        app.state.amule_api = fake
        csrf = login(client)

        assert client.get("/admin/downloads").json()["shared"] == fake.shared_items
        first = client.request(
            "DELETE",
            "/admin/library",
            headers={"X-CSRF-Token": csrf},
            json={"hashes": [fake.file_hash]},
        )
        assert first.status_code == 200
        assert not (media_root / "finished.mkv").exists()
        assert fake.reloads == 1

        # aMule may temporarily retain this item after its asynchronous reload,
        # but it must not be returned to the manager without a real media file.
        assert client.get("/admin/downloads").json()["shared"] == []

        repeat = client.request(
            "DELETE",
            "/admin/library",
            headers={"X-CSRF-Token": csrf},
            json={"hashes": [fake.file_hash]},
        )
        assert repeat.status_code == 200
        assert repeat.json() == {"results": [{"id": fake.file_hash, "ok": True}]}
        assert fake.reloads == 2
    get_settings.cache_clear()


def test_completed_library_delete_rejects_a_shared_path_outside_media_roots(monkeypatch, tmp_path):
    configure_admin(monkeypatch)
    media_root = tmp_path / "incoming"
    outside_root = tmp_path / "outside"
    media_root.mkdir()
    outside_root.mkdir()
    monkeypatch.setenv("AMULIO_ALLOWED_MEDIA_ROOTS", str(media_root))
    get_settings.cache_clear()
    with TestClient(app) as client:
        fake = StaleSharedLibraryApi(outside_root)
        app.state.amule_api = fake
        csrf = login(client)
        response = client.request(
            "DELETE",
            "/admin/library",
            headers={"X-CSRF-Token": csrf},
            json={"hashes": [fake.file_hash]},
        )
        assert response.status_code == 403
        assert (outside_root / "finished.mkv").exists()
        assert fake.reloads == 0
    get_settings.cache_clear()
