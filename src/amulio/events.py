import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from amulio.amule_api import AmuleApiClient, AmuleApiError
from amulio.cache import CandidateCache


def update_file_state(event_name: str, payload: dict[str, Any], cache: CandidateCache) -> None:
    file_hash = payload.get("hash")
    if not isinstance(file_hash, str):
        return
    if event_name == "download_removed":
        cache.set_file_state(file_hash, "removed")
        return
    if event_name.startswith("shared_"):
        state = "ready" if payload.get("path") != "[PartFile]" else "downloading"
        cache.set_file_state(file_hash, state)
        return
    if event_name.startswith("download_"):
        state = "ready" if payload.get("status") == "completed" else "downloading"
        cache.set_file_state(file_hash, state)


async def monitor_events(
    api: AmuleApiClient,
    cache: CandidateCache,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Reconnect forever; normal playback still checks amuleapi before opening a file."""
    while True:
        try:
            async for event_name, payload in api.events():
                update_file_state(event_name, payload, cache)
        except (TimeoutError, AmuleApiError, httpx.HTTPError, OSError):
            await sleep(3)
        except asyncio.CancelledError:
            raise
        else:
            await sleep(1)


async def stop_monitor(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
