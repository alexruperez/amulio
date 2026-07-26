from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
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
    amule_api_admin_password: SecretStr = Field(
        min_length=1,
        validation_alias="AMULE_API_ADMIN_PASSWORD",
    )
    cinemeta_base_url: AnyHttpUrl = "https://v3-cinemeta.strem.io/"
    search_wait_seconds: float = Field(default=1.0, ge=0, le=10)
    candidate_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    negative_candidate_ttl_seconds: int = Field(default=120, ge=10, le=3600)

    @property
    def media_roots(self) -> tuple[str, ...]:
        return tuple(root.strip() for root in self.allowed_media_roots.split(",") if root.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
