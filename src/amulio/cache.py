import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from amulio.models import Candidate


@dataclass(frozen=True)
class FileState:
    state: str
    status: str | None
    percent: float | None
    speed_bps: int | None
    sources_total: int | None
    updated_at: int


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
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS file_state (
                file_hash TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                status TEXT,
                percent REAL,
                speed_bps INTEGER,
                sources_total INTEGER,
                updated_at INTEGER NOT NULL
            )
            """
        )
        existing_columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(file_state)")
        }
        for column, definition in (
            ("status", "TEXT"),
            ("percent", "REAL"),
            ("speed_bps", "INTEGER"),
            ("sources_total", "INTEGER"),
        ):
            if column not in existing_columns:
                self._connection.execute(f"ALTER TABLE file_state ADD COLUMN {column} {definition}")
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

    def delete(self, media_key: str) -> None:
        """Discard a cached stream listing that is no longer valid."""
        self._connection.execute("DELETE FROM stream_cache WHERE media_key = ?", (media_key,))
        self._connection.commit()

    def set_file_state(
        self,
        file_hash: str,
        state: str,
        *,
        status: str | None = None,
        percent: float | None = None,
        speed_bps: int | None = None,
        sources_total: int | None = None,
    ) -> None:
        self._connection.execute(
            """
                INSERT INTO file_state
                    (file_hash, state, status, percent, speed_bps, sources_total, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_hash) DO UPDATE SET
                    state = excluded.state,
                    status = excluded.status,
                    percent = excluded.percent,
                    speed_bps = excluded.speed_bps,
                    sources_total = excluded.sources_total,
                    updated_at = excluded.updated_at
            """,
            (file_hash.lower(), state, status, percent, speed_bps, sources_total, int(time.time())),
        )
        self._connection.commit()

    def clear_file_states(self) -> None:
        self._connection.execute("DELETE FROM file_state")
        self._connection.commit()

    def file_states(self, file_hashes: list[str]) -> dict[str, str]:
        if not file_hashes:
            return {}
        placeholders = ",".join("?" for _ in file_hashes)
        rows = self._connection.execute(
            f"SELECT file_hash, state FROM file_state WHERE file_hash IN ({placeholders})",
            [file_hash.lower() for file_hash in file_hashes],
        ).fetchall()
        return dict(rows)

    def file_state(self, file_hash: str) -> FileState | None:
        row = self._connection.execute(
            """
            SELECT state, status, percent, speed_bps, sources_total, updated_at
            FROM file_state WHERE file_hash = ?
            """,
            (file_hash.lower(),),
        ).fetchone()
        return FileState(*row) if row is not None else None

    def file_state_details(self, file_hashes: list[str]) -> dict[str, FileState]:
        if not file_hashes:
            return {}
        placeholders = ",".join("?" for _ in file_hashes)
        rows = self._connection.execute(
            f"""
            SELECT file_hash, state, status, percent, speed_bps, sources_total, updated_at
            FROM file_state WHERE file_hash IN ({placeholders})
            """,
            [file_hash.lower() for file_hash in file_hashes],
        ).fetchall()
        return {file_hash: FileState(*state) for file_hash, *state in rows}
