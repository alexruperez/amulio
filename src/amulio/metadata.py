import re
import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel


@dataclass(frozen=True)
class TitleVariant:
    title: str
    language: str | None = None


class MediaMetadata(BaseModel):
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    aliases: tuple[TitleVariant, ...] = ()

    @property
    def search_query(self) -> str:
        return self.search_queries(limit=1)[0]

    def search_queries(
        self, *, preferred_languages: tuple[str, ...] = (), limit: int = 3
    ) -> tuple[str, ...]:
        language_order = {language: index for index, language in enumerate(preferred_languages)}
        aliases = sorted(
            self.aliases,
            key=lambda alias: language_order.get(
                (alias.language or "").lower(), len(language_order)
            ),
        )
        titles = [self.title, *(alias.title for alias in aliases)]
        queries: list[str] = []
        seen: set[str] = set()
        for title in titles:
            normalized = " ".join(title.split()).casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            query = title
            if self.season is not None and self.episode is not None:
                query = f"{query} S{self.season:02d}E{self.episode:02d}"
            elif self.year is not None:
                query = f"{query} {self.year}"
            queries.append(query)
            if len(queries) == limit:
                break
        return tuple(queries)

    @property
    def titles(self) -> tuple[str, ...]:
        return (self.title, *(alias.title for alias in self.aliases))


@dataclass(frozen=True)
class _CachedMetadata:
    metadata: MediaMetadata
    expires_at: float


def _title_variants(meta: dict) -> tuple[TitleVariant, ...]:
    variants: list[TitleVariant] = []
    for key in ("originalTitle", "originalName", "original_name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            variants.append(TitleVariant(title=value.strip()))
    for key in ("aliases", "titles", "translations"):
        values = meta.get(key, [])
        if isinstance(values, dict):
            values = values.values()
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if isinstance(value, str) and value.strip():
                variants.append(TitleVariant(title=value.strip()))
            elif isinstance(value, dict):
                title = next(
                    (
                        value.get(title_key)
                        for title_key in ("title", "name", "value")
                        if isinstance(value.get(title_key), str) and value[title_key].strip()
                    ),
                    None,
                )
                if isinstance(title, str):
                    language = next(
                        (
                            value.get(language_key)
                            for language_key in ("language", "lang", "locale")
                            if isinstance(value.get(language_key), str)
                        ),
                        None,
                    )
                    variants.append(TitleVariant(title=title.strip(), language=language))
    return tuple(variants)


class MetadataError(RuntimeError):
    pass


class CinemetaClient:
    def __init__(self, *, base_url: str, metadata_ttl_seconds: int = 3600) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", timeout=10)
        self._metadata_ttl_seconds = metadata_ttl_seconds
        self._cache: dict[str, _CachedMetadata] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def resolve(self, media_type: str, media_id: str) -> MediaMetadata:
        cache_key = f"{media_type}:{media_id}"
        cached = self._cache.get(cache_key)
        if cached is not None and cached.expires_at > time.monotonic():
            return cached.metadata
        parts = media_id.split(":")
        imdb_id = parts[0]
        response = await self._client.get(f"meta/{media_type}/{imdb_id}.json")
        if response.is_error:
            raise MetadataError(f"Cinemeta metadata lookup failed ({response.status_code})")
        meta = response.json().get("meta")
        title = meta.get("name") if isinstance(meta, dict) else None
        if not isinstance(title, str) or not title.strip():
            raise MetadataError("Cinemeta metadata response did not include a title")
        release_info = meta.get("releaseInfo", "")
        year_match = re.search(r"\b(19|20)\d{2}\b", str(release_info))
        season = episode = None
        if media_type == "series" and len(parts) == 3:
            try:
                season, episode = int(parts[1]), int(parts[2])
            except ValueError as exc:
                raise MetadataError("Invalid Stremio episode id") from exc
        metadata = MediaMetadata(
            title=title.strip(),
            year=int(year_match.group()) if year_match else None,
            season=season,
            episode=episode,
            aliases=_title_variants(meta),
        )
        self._cache[cache_key] = _CachedMetadata(
            metadata=metadata,
            expires_at=time.monotonic() + self._metadata_ttl_seconds,
        )
        return metadata
