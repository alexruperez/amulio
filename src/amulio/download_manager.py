"""Validation helpers for the administrator-only download manager."""

import re
from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException, status

HASH_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MAX_SELECTION = 500


def normalize_hashes(hashes: Iterable[str]) -> list[str]:
    """Validate and canonicalize a bounded, duplicate-free MD4 selection."""
    values = list(hashes)
    if not values or len(values) > MAX_SELECTION:
        raise ValueError(f"Select between 1 and {MAX_SELECTION} downloads")
    normalized = [value.lower() for value in values]
    if any(not HASH_PATTERN.fullmatch(value) for value in normalized):
        raise ValueError("Each selection must be a 32-character hexadecimal download hash")
    if len(set(normalized)) != len(normalized):
        raise ValueError("A download may only be selected once")
    return normalized


def active_hashes(downloads: Iterable[dict[str, Any]]) -> set[str]:
    """Return only valid identifiers for non-completed queue entries."""
    return {
        item["hash"].lower()
        for item in downloads
        if isinstance(item.get("hash"), str)
        and HASH_PATTERN.fullmatch(item["hash"].lower())
        and item.get("status") != "completed"
    }


def require_active_selection(hashes: list[str], downloads: Iterable[dict[str, Any]]) -> None:
    """Reject stale, unknown, or completed selections before mutating aMule."""
    unavailable = sorted(set(hashes) - active_hashes(downloads))
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more selected downloads are no longer active",
        )


def public_download(item: dict[str, Any]) -> dict[str, Any]:
    """Return the small queue projection needed by the browser manager."""
    file_hash = item.get("hash")
    if not isinstance(file_hash, str) or not HASH_PATTERN.fullmatch(file_hash.lower()):
        raise ValueError("amuleapi returned a download with an invalid hash")
    name = item.get("name")
    size = item.get("size")
    normalized_size = size if isinstance(size, int) and size >= 0 else 0
    size_done = item.get("size_done")
    normalized_size_done = size_done if isinstance(size_done, int) else 0
    return {
        "hash": file_hash.lower(),
        "name": name if isinstance(name, str) else "Unnamed download",
        "size": normalized_size,
        "size_done": max(0, min(normalized_size, normalized_size_done)),
        "speed_bps": item.get("speed_bps") if isinstance(item.get("speed_bps"), int) else 0,
        "status": item.get("status") if isinstance(item.get("status"), str) else "unknown",
    }


def public_shared_file(item: dict[str, Any]) -> dict[str, Any]:
    """Return a read-only library projection; no deletion capability is exposed."""
    file_hash = item.get("hash")
    if not isinstance(file_hash, str) or not HASH_PATTERN.fullmatch(file_hash.lower()):
        raise ValueError("amuleapi returned a shared file with an invalid hash")
    name = item.get("name")
    size = item.get("size")
    return {
        "hash": file_hash.lower(),
        "name": name if isinstance(name, str) else "Unnamed shared file",
        "size": size if isinstance(size, int) and size >= 0 else 0,
    }
