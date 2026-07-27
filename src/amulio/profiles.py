import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ProfilePreferences(BaseModel):
    """User-controlled, non-secret settings carried by an addon profile."""

    schema_version: Literal[1] = 1
    ui_language: Literal["en", "es"] = "en"
    search_languages: tuple[str, ...] = ("en", "es")
    allow_season_packs: bool = False
    result_limit: int = Field(default=10, ge=1, le=50)
    max_size_gb: float | None = Field(default=None, gt=0, le=100)
    show_stream_size: bool = True
    show_stream_sources: bool = True
    show_stream_language: bool = True
    show_stream_technical_details: bool = True


class AddonProfile(BaseModel):
    id: str = Field(min_length=24, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    preferences: ProfilePreferences
    created_at: int
    updated_at: int


class ProfileStore:
    """Persist non-secret addon profiles and make them individually revocable."""

    def __init__(self, database_path: str):
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS addon_profile (
                profile_id TEXT PRIMARY KEY,
                preferences_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                revoked_at INTEGER
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def create(self, preferences: ProfilePreferences | None = None) -> AddonProfile:
        now = int(time.time())
        profile = AddonProfile(
            id=secrets.token_urlsafe(24),
            preferences=preferences or ProfilePreferences(),
            created_at=now,
            updated_at=now,
        )
        self._connection.execute(
            """
            INSERT INTO addon_profile (profile_id, preferences_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                profile.id,
                profile.preferences.model_dump_json(),
                profile.created_at,
                profile.updated_at,
            ),
        )
        self._connection.commit()
        return profile

    def get(self, profile_id: str) -> AddonProfile | None:
        row = self._connection.execute(
            """
            SELECT preferences_json, created_at, updated_at
            FROM addon_profile
            WHERE profile_id = ? AND revoked_at IS NULL
            """,
            (profile_id,),
        ).fetchone()
        if row is None:
            return None
        preferences_json, created_at, updated_at = row
        return AddonProfile(
            id=profile_id,
            preferences=ProfilePreferences.model_validate(json.loads(preferences_json)),
            created_at=created_at,
            updated_at=updated_at,
        )

    def update(self, profile_id: str, preferences: ProfilePreferences) -> AddonProfile | None:
        updated_at = int(time.time())
        cursor = self._connection.execute(
            """
            UPDATE addon_profile
            SET preferences_json = ?, updated_at = ?
            WHERE profile_id = ? AND revoked_at IS NULL
            """,
            (preferences.model_dump_json(), updated_at, profile_id),
        )
        self._connection.commit()
        if cursor.rowcount != 1:
            return None
        return self.get(profile_id)

    def revoke(self, profile_id: str) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE addon_profile
            SET revoked_at = ?
            WHERE profile_id = ? AND revoked_at IS NULL
            """,
            (int(time.time()), profile_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def rotate(self, profile_id: str) -> AddonProfile | None:
        """Create a replacement profile and atomically revoke the old one."""
        profile = self.get(profile_id)
        if profile is None:
            return None
        replacement = AddonProfile(
            id=secrets.token_urlsafe(24),
            preferences=profile.preferences,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE addon_profile
                SET revoked_at = ?
                WHERE profile_id = ? AND revoked_at IS NULL
                """,
                (replacement.created_at, profile_id),
            )
            if cursor.rowcount != 1:
                return None
            self._connection.execute(
                """
                INSERT INTO addon_profile (profile_id, preferences_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    replacement.id,
                    replacement.preferences.model_dump_json(),
                    replacement.created_at,
                    replacement.updated_at,
                ),
            )
        return replacement
