from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AMULIO_",
        extra="ignore",
    )

    public_url: AnyHttpUrl = "http://127.0.0.1:8000"
    install_token: SecretStr = Field(min_length=24)
    token_secret: SecretStr = Field(min_length=32)
    allowed_media_roots: str = "/data/incoming"
    database_path: str = "data/amulio.sqlite3"
    amule_api_base_url: AnyHttpUrl = Field(
        default="http://127.0.0.1:4713/api/v0",
        validation_alias="AMULE_API_BASE_URL",
    )
    amule_api_admin_password: SecretStr | None = Field(
        default=None,
        validation_alias="AMULE_API_ADMIN_PASSWORD",
    )
    amule_api_admin_password_file: str | None = Field(
        default=None,
        validation_alias="AMULE_API_ADMIN_PASSWORD_FILE",
    )
    cinemeta_base_url: AnyHttpUrl = "https://v3-cinemeta.strem.io/"
    metadata_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    preferred_languages: str = "en,es"
    allowed_video_extensions: str = ".avi,.m4v,.mkv,.mov,.mp4,.mpeg,.mpg,.ts,.webm"
    denied_file_extensions: str = ".exe,.iso,.rar,.zip"
    allow_season_packs: bool = False
    search_query_limit: int = Field(default=3, ge=1, le=5)
    search_wait_seconds: float = Field(default=1.0, ge=0, le=10)
    search_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    candidate_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    negative_candidate_ttl_seconds: int = Field(default=120, ge=10, le=3600)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    manifest_rate_limit: int = Field(default=30, ge=1, le=10_000)
    stream_rate_limit: int = Field(default=30, ge=1, le=10_000)
    playback_rate_limit: int = Field(default=600, ge=1, le=100_000)

    @model_validator(mode="after")
    def load_amule_api_admin_password_file(self) -> "Settings":
        if self.amule_api_admin_password is not None:
            return self
        if not self.amule_api_admin_password_file:
            raise ValueError("Set AMULE_API_ADMIN_PASSWORD or AMULE_API_ADMIN_PASSWORD_FILE")
        try:
            password = Path(self.amule_api_admin_password_file).read_text().strip()
        except OSError as exc:
            raise ValueError("Could not read AMULE_API_ADMIN_PASSWORD_FILE") from exc
        if not password:
            raise ValueError("AMULE_API_ADMIN_PASSWORD_FILE must not be empty")
        self.amule_api_admin_password = SecretStr(password)
        return self

    @property
    def media_roots(self) -> tuple[str, ...]:
        return tuple(root.strip() for root in self.allowed_media_roots.split(",") if root.strip())

    @property
    def search_languages(self) -> tuple[str, ...]:
        return tuple(
            language.strip().lower()
            for language in self.preferred_languages.split(",")
            if language.strip()
        )

    @staticmethod
    def _extensions(value: str) -> tuple[str, ...]:
        return tuple(
            extension if extension.startswith(".") else f".{extension}"
            for item in value.split(",")
            if (extension := item.strip().lower())
        )

    @property
    def allowed_extensions(self) -> tuple[str, ...]:
        return self._extensions(self.allowed_video_extensions)

    @property
    def denied_extensions(self) -> tuple[str, ...]:
        return self._extensions(self.denied_file_extensions)


@lru_cache
def get_settings() -> Settings:
    return Settings()
