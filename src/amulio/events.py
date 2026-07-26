import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from amulio.amule_api import AmuleApiClient, AmuleApiError
from amulio.cache import CandidateCache


@dataclass
class MonitorHealth:
    connected: bool = False
    last_sync_at: float | None = None
    last_event_at: float | None = None
    last_error: str | None = None
    reconnects: int = 0

    def as_dict(self) -> dict[str, bool | float | int | str | None]:
        return {
            "connected": self.connected,
            "last_sync_at": self.last_sync_at,
            "last_event_at": self.last_event_at,
            "last_error": self.last_error,
            "reconnects": self.reconnects,
        }


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) else None


def update_file_state(event_name: str, payload: dict[str, Any], cache: CandidateCache) -> None:
    file_hash = payload.get("hash")
    if not isinstance(file_hash, str):
        return
    if event_name == "download_removed":
        cache.set_file_state(file_hash, "removed", status="removed")
        return
    if event_name.startswith("shared_"):
        state = "ready" if payload.get("path") != "[PartFile]" else "downloading"
        cache.set_file_state(file_hash, state, status="completed" if state == "ready" else None)
        return
    if event_name.startswith("download_"):
        status = payload.get("status") if isinstance(payload.get("status"), str) else None
        progress = payload.get("progress")
        sources = payload.get("sources")
        percent = _number(progress.get("percent")) if isinstance(progress, dict) else None
        sources_total = _integer(sources.get("total")) if isinstance(sources, dict) else None
        state = "ready" if status == "completed" else "downloading"
        cache.set_file_state(
            file_hash,
            state,
            status=status,
            percent=percent,
            speed_bps=_integer(payload.get("speed_bps")),
            sources_total=sources_total,
        )


def _apply_snapshot(
    downloads: list[dict[str, Any]], shared_files: list[dict[str, Any]], cache: CandidateCache
) -> None:
    cache.clear_file_states()
    for download in downloads:
        update_file_state("download_updated", download, cache)
    for shared_file in shared_files:
        update_file_state("shared_updated", shared_file, cache)


async def _collect_events(
    api: AmuleApiClient,
    events: asyncio.Queue[tuple[str, dict[str, Any]] | BaseException | None],
    connected: asyncio.Event,
) -> None:
    try:
        async for event_name, payload in api.events(connected=connected):
            await events.put((event_name, payload))
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        await events.put(exc)
    else:
        await events.put(None)


async def _wait_for_connection(collector: asyncio.Task[None], connected: asyncio.Event) -> None:
    connection_waiter = asyncio.create_task(connected.wait())
    done, _ = await asyncio.wait(
        {collector, connection_waiter}, return_when=asyncio.FIRST_COMPLETED
    )
    if connection_waiter not in done:
        connection_waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await connection_waiter
    if collector in done:
        await collector


async def monitor_events(
    api: AmuleApiClient,
    cache: CandidateCache,
    *,
    health: MonitorHealth | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Maintain a local state cache using snapshot-then-stream reconciliation."""
    monitor_health = health or MonitorHealth()
    while True:
        collector: asyncio.Task[None] | None = None
        try:
            events: asyncio.Queue[tuple[str, dict[str, Any]] | BaseException | None] = (
                asyncio.Queue()
            )
            connected = asyncio.Event()
            collector = asyncio.create_task(_collect_events(api, events, connected))
            await _wait_for_connection(collector, connected)
            monitor_health.connected = True
            downloads, shared_files = await asyncio.gather(api.downloads(), api.shared_files())
            _apply_snapshot(downloads, shared_files, cache)
            monitor_health.last_sync_at = time.time()

            while True:
                event = await events.get()
                if event is None:
                    raise OSError("amuleapi event stream closed")
                if isinstance(event, BaseException):
                    raise event
                event_name, payload = event
                if event_name == "resync":
                    monitor_health.connected = False
                    downloads, shared_files = await asyncio.gather(
                        api.downloads(), api.shared_files()
                    )
                    _apply_snapshot(downloads, shared_files, cache)
                    monitor_health.last_sync_at = time.time()
                    monitor_health.connected = True
                    continue
                update_file_state(event_name, payload, cache)
                monitor_health.last_event_at = time.time()
        except (TimeoutError, AmuleApiError, httpx.HTTPError, OSError) as exc:
            monitor_health.connected = False
            monitor_health.last_error = str(exc)
            monitor_health.reconnects += 1
            await sleep(3)
        except asyncio.CancelledError:
            raise
        finally:
            if collector is not None and not collector.done():
                collector.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await collector


async def stop_monitor(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
