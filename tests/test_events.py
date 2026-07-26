import asyncio

from amulio.cache import CandidateCache
from amulio.events import MonitorHealth, monitor_events, stop_monitor, update_file_state


def test_download_and_shared_events_update_local_file_state(tmp_path):
    cache = CandidateCache(str(tmp_path / "cache.sqlite3"))
    file_hash = "a" * 32

    update_file_state("download_updated", {"hash": file_hash, "status": "downloading"}, cache)
    assert cache.file_states([file_hash]) == {file_hash: "downloading"}

    update_file_state("shared_updated", {"hash": file_hash, "path": "/data/incoming"}, cache)
    assert cache.file_states([file_hash]) == {file_hash: "ready"}
    cache.close()


async def test_monitor_snapshots_then_applies_buffered_download_events(tmp_path):
    file_hash = "a" * 32
    hold_open = asyncio.Event()

    class FakeApi:
        async def events(self, *, connected: asyncio.Event):
            connected.set()
            yield (
                "download_updated",
                {
                    "hash": file_hash,
                    "status": "downloading",
                    "speed_bps": 500,
                    "sources": {"total": 9},
                    "progress": {"percent": 50.0},
                },
            )
            await hold_open.wait()

        async def downloads(self):
            return [
                {
                    "hash": file_hash,
                    "status": "downloading",
                    "speed_bps": 100,
                    "sources": {"total": 2},
                    "progress": {"percent": 10.0},
                }
            ]

        async def shared_files(self):
            return []

    cache = CandidateCache(str(tmp_path / "cache.sqlite3"))
    health = MonitorHealth()
    task = asyncio.create_task(monitor_events(FakeApi(), cache, health=health))
    try:
        for _ in range(50):
            await asyncio.sleep(0)
            state = cache.file_state(file_hash)
            if state is not None and state.percent == 50:
                break
        else:
            raise AssertionError("The buffered event was not applied")
    finally:
        hold_open.set()
        await stop_monitor(task)
        cache.close()

    assert state.state == "downloading"
    assert state.percent == 50
    assert state.speed_bps == 500
    assert state.sources_total == 9
    assert health.connected is True
    assert health.last_sync_at is not None
    assert health.last_event_at is not None


async def test_monitor_resync_replaces_stale_state_with_a_new_snapshot(tmp_path):
    file_hash = "b" * 32
    hold_open = asyncio.Event()

    class FakeApi:
        snapshots = 0

        async def events(self, *, connected: asyncio.Event):
            connected.set()
            yield "resync", {"reason": "gap"}
            await hold_open.wait()

        async def downloads(self):
            self.snapshots += 1
            return [
                {
                    "hash": file_hash,
                    "status": "downloading",
                    "speed_bps": 100 * self.snapshots,
                    "sources": {"total": self.snapshots},
                    "progress": {"percent": 20.0 * self.snapshots},
                }
            ]

        async def shared_files(self):
            return []

    api = FakeApi()
    cache = CandidateCache(str(tmp_path / "cache.sqlite3"))
    task = asyncio.create_task(monitor_events(api, cache))
    try:
        for _ in range(50):
            await asyncio.sleep(0)
            state = cache.file_state(file_hash)
            if state is not None and state.percent == 40:
                break
        else:
            raise AssertionError("The resync snapshot was not applied")
    finally:
        hold_open.set()
        await stop_monitor(task)
        cache.close()

    assert api.snapshots == 2
    assert state.speed_bps == 200
    assert state.sources_total == 2


async def test_monitor_reconnects_after_the_event_stream_disconnects(tmp_path):
    file_hash = "c" * 32
    hold_open = asyncio.Event()

    class FakeApi:
        connections = 0

        async def events(self, *, connected: asyncio.Event):
            self.connections += 1
            connected.set()
            if self.connections == 1:
                raise OSError("connection dropped")
            await hold_open.wait()
            yield "download_updated", {"hash": file_hash, "status": "downloading"}

        async def downloads(self):
            return [{"hash": file_hash, "status": "downloading"}]

        async def shared_files(self):
            return []

    async def no_delay(_: float) -> None:
        await asyncio.sleep(0)

    api = FakeApi()
    cache = CandidateCache(str(tmp_path / "cache.sqlite3"))
    health = MonitorHealth()
    task = asyncio.create_task(monitor_events(api, cache, health=health, sleep=no_delay))
    try:
        for _ in range(50):
            await asyncio.sleep(0)
            if health.reconnects == 1 and api.connections == 2 and health.connected:
                break
        else:
            raise AssertionError("The monitor did not reconnect")
    finally:
        hold_open.set()
        await stop_monitor(task)
        cache.close()

    assert health.connected is True
    assert health.last_error == "connection dropped"
