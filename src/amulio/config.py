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
    admin_password: SecretStr | None = Field(
        default=None, min_length=16, validation_alias="AMULIO_ADMIN_PASSWORD"
    )
    admin_password_file: str | None = Field(
        default=None, validation_alias="AMULIO_ADMIN_PASSWORD_FILE"
    )
    admin_session_ttl_seconds: int = Field(default=28_800, ge=300, le=86_400)
    metrics_token: SecretStr | None = Field(default=None, min_length=24)
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
    admin_login_rate_limit: int = Field(default=10, ge=1, le=100)
    manifest_rate_limit: int = Field(default=30, ge=1, le=10_000)
    stream_rate_limit: int = Field(default=30, ge=1, le=10_000)
    playback_rate_limit: int = Field(default=600, ge=1, le=100_000)
    # Opt-in only: deterministic, legal end-to-end fixture for self-hosted
    # deployments. It never has a default and is not intended as a catalogue.
    e2e_fixture_media_id: str | None = None
    e2e_fixture_ed2k_link: str | None = None

    @model_validator(mode="after")
    def load_password_files(self) -> "Settings":
        if self.admin_password is None and self.admin_password_file:
            admin_password = self._read_secret_file(
                self.admin_password_file, variable="AMULIO_ADMIN_PASSWORD_FILE"
            )
            if len(admin_password) < 16:
                raise ValueError("AMULIO_ADMIN_PASSWORD_FILE must contain at least 16 characters")
            self.admin_password = SecretStr(admin_password)
        if self.amule_api_admin_password is None:
            if not self.amule_api_admin_password_file:
                raise ValueError("Set AMULE_API_ADMIN_PASSWORD or AMULE_API_ADMIN_PASSWORD_FILE")
            self.amule_api_admin_password = SecretStr(
                self._read_secret_file(
                    self.amule_api_admin_password_file,
                    variable="AMULE_API_ADMIN_PASSWORD_FILE",
                )
            )
        return self

    @staticmethod
    def _read_secret_file(path: str, *, variable: str) -> str:
        try:
            password = Path(path).read_text().strip()
        except OSError as exc:
            raise ValueError(f"Could not read {variable}") from exc
        if not password:
            raise ValueError(f"{variable} must not be empty")
        return password

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
