import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from amulio.amule_api import AmuleApiClient, AmuleApiError
from amulio.cache import CandidateCache
from amulio.config import Settings, get_settings
from amulio.events import monitor_events, stop_monitor
from amulio.metadata import CinemetaClient, MetadataError
from amulio.models import Candidate
from amulio.ranking import rank_results
from amulio.search_locks import MediaSearchLocks
from amulio.tokens import InvalidToken, sign, verify


def _get_api(request: Request) -> AmuleApiClient:
    return request.app.state.amule_api


ApiClient = Annotated[AmuleApiClient, Depends(_get_api)]


def _get_metadata(request: Request) -> CinemetaClient:
    return request.app.state.metadata


MetadataClient = Annotated[CinemetaClient, Depends(_get_metadata)]


def _get_cache(request: Request) -> CandidateCache:
    return request.app.state.cache


Cache = Annotated[CandidateCache, Depends(_get_cache)]


def _get_search_locks(request: Request) -> MediaSearchLocks:
    return request.app.state.search_locks


SearchLocks = Annotated[MediaSearchLocks, Depends(_get_search_locks)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.amule_api = AmuleApiClient(
        base_url=str(settings.amule_api_base_url),
        admin_password=settings.amule_api_admin_password.get_secret_value(),
    )
    app.state.metadata = CinemetaClient(
        base_url=str(settings.cinemeta_base_url),
        metadata_ttl_seconds=settings.metadata_cache_ttl_seconds,
    )
    app.state.cache = CandidateCache(settings.database_path)
    app.state.search_locks = MediaSearchLocks()
    app.state.event_monitor = asyncio.create_task(
        monitor_events(app.state.amule_api, app.state.cache),
        name="amulio-amuleapi-events",
    )
    yield
    await stop_monitor(app.state.event_monitor)
    await app.state.amule_api.close()
    await app.state.metadata.close()
    app.state.cache.close()


app = FastAPI(title="aMulio", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # The installation URL is a high-entropy bearer capability and no cookies are used.
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _require_install_token(token: str, settings: Settings) -> None:
    if token != settings.install_token.get_secret_value():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _state_marker(state: str | None) -> str:
    if state == "ready":
        return "✅"
    if state == "downloading":
        return "⬇️"
    return "🧲"


def _stream_object(candidate: Candidate, request: Request, *, state: str | None = None) -> dict:
    settings = _settings(request)
    token = sign(
        {"candidate": candidate.model_dump()},
        secret=settings.token_secret.get_secret_value(),
        ttl_seconds=settings.candidate_ttl_seconds,
    )
    return {
        "name": f"{_state_marker(state)} aMulio · {candidate.quality or 'video'}",
        "description": (
            f"{candidate.name}\n"
            f"💾 {candidate.size / 1_000_000_000:.2f} GB · "
            f"👥 {candidate.sources_total} fuentes "
            f"({candidate.sources_complete} completas)"
        ),
        "url": f"{str(settings.public_url).rstrip('/')}/play/{token}",
        "behaviorHints": {
            "filename": candidate.name,
            "videoSize": candidate.size,
            "notWebReady": True,
            "bingeGroup": f"amulio|{candidate.hash}",
        },
    }


def _stream_response(candidates: list[Candidate], request: Request, cache: CandidateCache) -> dict:
    states = cache.file_states([candidate.hash for candidate in candidates])
    return {
        "streams": [
            _stream_object(candidate, request, state=states.get(candidate.hash))
            for candidate in candidates
        ]
    }


def _safe_media_path(file_path: str, *, settings: Settings) -> Path:
    resolved_path = Path(file_path).resolve(strict=True)
    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="The aMule media file is unavailable")
    roots = [Path(root).resolve(strict=True) for root in settings.media_roots]
    if not any(resolved_path.is_relative_to(root) for root in roots):
        raise HTTPException(status_code=403, detail="The media file is outside an allowed root")
    return resolved_path


async def _resolve_completed_file(candidate: Candidate, api: AmuleApiClient):
    shared = await api.shared_file(candidate.hash)
    if shared:
        return shared
    return await api.completed_download(candidate.hash)


async def _discover_candidates(
    *,
    media_type: str,
    media_id: str,
    api: AmuleApiClient,
    metadata: CinemetaClient,
    cache: CandidateCache,
    settings: Settings,
    search_locks: MediaSearchLocks,
) -> list[Candidate]:
    # Stremio uses tt<id>:<season>:<episode> for episodes, making this key
    # independently serialise every movie and episode lookup.
    media_key = f"{media_type}:{media_id}"
    cached = cache.get(media_key)
    if cached is not None:
        return cached

    async with search_locks.acquire(media_key):
        # A request that waited for an identical search should reuse its result.
        cached = cache.get(media_key)
        if cached is not None:
            return cached

        try:
            async with asyncio.timeout(settings.search_timeout_seconds):
                resolved = await metadata.resolve(media_type, media_id)
                queries = resolved.search_queries(
                    preferred_languages=settings.search_languages,
                    limit=settings.search_query_limit,
                )
                search_ids = await asyncio.gather(
                    *(
                        api.start_search(query, kind=kind)
                        for query in queries
                        for kind in ("global", "kad")
                    )
                )
                await asyncio.sleep(settings.search_wait_seconds)
                result_sets = await asyncio.gather(
                    *(api.search_results(search_id) for search_id in search_ids)
                )
        except TimeoutError as exc:
            raise AmuleApiError("aMule search timed out") from exc
        candidates = rank_results(
            [result for result_set in result_sets for result in result_set],
            resolved,
        )
        cache.put(
            media_key,
            candidates,
            ttl_seconds=(
                settings.candidate_ttl_seconds
                if candidates
                else settings.negative_candidate_ttl_seconds
            ),
        )
        return candidates


@app.get("/health")
async def health(api: ApiClient):
    try:
        return {"ok": True, "amule": await api.health()}
    except AmuleApiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/configure")


@app.get("/configure", response_class=HTMLResponse)
async def configure(request: Request):
    settings = _settings(request)
    manifest_url = (
        f"{str(settings.public_url).rstrip('/')}/"
        f"{settings.install_token.get_secret_value()}/manifest.json"
    )
    return f"""<!doctype html><html><body><h1>aMulio</h1>
    <p>Instala este addon privado en Stremio:</p><code>{manifest_url}</code></body></html>"""


@app.get("/{installation_token}/manifest.json")
async def manifest(installation_token: str, request: Request):
    settings = _settings(request)
    _require_install_token(installation_token, settings)
    return {
        "id": "com.alexruperez.amulio",
        "version": "0.1.0",
        "name": "aMulio",
        "description": "Busca contenido eD2K/Kad y reproduce archivos completados de aMule.",
        "catalogs": [],
        "resources": [{"name": "stream", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
        "types": ["movie", "series"],
        "behaviorHints": {"configurable": True, "configurationRequired": True, "p2p": True},
    }


@app.get("/{installation_token}/stream/{media_type}/{media_id}.json")
async def streams(
    installation_token: str,
    media_type: str,
    media_id: str,
    request: Request,
    response: Response,
    api: ApiClient,
    metadata: MetadataClient,
    cache: Cache,
    search_locks: SearchLocks,
):
    settings = _settings(request)
    _require_install_token(installation_token, settings)
    response.headers["Cache-Control"] = "no-store"
    if media_type not in {"movie", "series"} or not media_id.startswith("tt"):
        return {"streams": []}

    try:
        candidates = await _discover_candidates(
            media_type=media_type,
            media_id=media_id,
            api=api,
            metadata=metadata,
            cache=cache,
            settings=settings,
            search_locks=search_locks,
        )
    except (AmuleApiError, MetadataError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _stream_response(candidates, request, cache)


@app.get("/play/{token}")
async def play(token: str, request: Request, api: ApiClient):
    settings = _settings(request)
    try:
        candidate = Candidate.model_validate(
            verify(token, secret=settings.token_secret.get_secret_value())["candidate"]
        )
    except (InvalidToken, KeyError):
        raise HTTPException(status_code=404) from None

    try:
        if await _resolve_completed_file(candidate, api):
            return RedirectResponse(f"/file/{token}", status_code=307)
        await api.add_download(candidate.ed2k_link)
    except AmuleApiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    raise HTTPException(
        status_code=202,
        detail="Download queued in aMule. Retry this stream once the file is complete.",
    )


@app.api_route("/file/{token}", methods=["GET", "HEAD"])
async def file(token: str, request: Request, api: ApiClient):
    settings = _settings(request)
    try:
        candidate = Candidate.model_validate(
            verify(token, secret=settings.token_secret.get_secret_value())["candidate"]
        )
    except (InvalidToken, KeyError):
        raise HTTPException(status_code=404) from None

    try:
        completed = await _resolve_completed_file(candidate, api)
    except AmuleApiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not completed:
        raise HTTPException(status_code=409, detail="The aMule download is not complete")
    if completed.size != candidate.size:
        raise HTTPException(
            status_code=409,
            detail="The completed file no longer matches this stream",
        )
    path = _safe_media_path(str(Path(completed.path) / completed.name), settings=settings)
    return FileResponse(path, filename=completed.name, content_disposition_type="inline")
