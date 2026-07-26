import json
import sqlite3
import time
from pathlib import Path

from amulio.models import Candidate


class CandidateCache:
    def __init__(self, path: str) -> None:
        database_path = Path(path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stream_cache (
                media_key TEXT PRIMARY KEY,
                candidates_json TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def get(self, media_key: str) -> list[Candidate] | None:
        row = self._connection.execute(
            "SELECT candidates_json FROM stream_cache WHERE media_key = ? AND expires_at > ?",
            (media_key, int(time.time())),
        ).fetchone()
        if row is None:
            return None
        return [Candidate.model_validate(item) for item in json.loads(row[0])]

    def put(self, media_key: str, candidates: list[Candidate], *, ttl_seconds: int) -> None:
        expires_at = int(time.time()) + ttl_seconds
        serialized = json.dumps([candidate.model_dump() for candidate in candidates])
        self._connection.execute(
            """
            INSERT INTO stream_cache (media_key, candidates_json, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(media_key) DO UPDATE SET
                candidates_json = excluded.candidates_json,
                expires_at = excluded.expires_at
            """,
            (media_key, serialized, expires_at),
        )
        self._connection.commit()
