import re

import httpx
from pydantic import BaseModel


class MediaMetadata(BaseModel):
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None

    @property
    def search_query(self) -> str:
        query = self.title
        if self.season is not None and self.episode is not None:
            return f"{query} S{self.season:02d}E{self.episode:02d}"
        if self.year is not None:
            return f"{query} {self.year}"
        return query


class MetadataError(RuntimeError):
    pass


class CinemetaClient:
    def __init__(self, *, base_url: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", timeout=10)

    async def close(self) -> None:
        await self._client.aclose()

    async def resolve(self, media_type: str, media_id: str) -> MediaMetadata:
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
        return MediaMetadata(
            title=title.strip(),
            year=int(year_match.group()) if year_match else None,
            season=season,
            episode=episode,
        )
