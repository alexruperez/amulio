import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse

from amulio.amule_api import AmuleApiClient, AmuleApiError
from amulio.cache import CandidateCache, FileState
from amulio.config import Settings, get_settings
from amulio.events import MonitorHealth, monitor_events, stop_monitor
from amulio.local_media import discover_local_media
from amulio.metadata import CinemetaClient, MetadataError
from amulio.models import Candidate
from amulio.observability import MetricsRegistry, configure_logging
from amulio.ranking import rank_results
from amulio.rate_limit import SlidingWindowRateLimiter
from amulio.search_locks import MediaSearchLocks
from amulio.status_videos import status_video
from amulio.tokens import InvalidToken, sign, verify

logger = logging.getLogger("amulio.app")


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
    configure_logging()
    settings = get_settings()
    app.state.settings = settings
    app.state.amule_api = AmuleApiClient(
        base_url=str(settings.amule_api_base_url),
        admin_password=settings.amule_api_admin_password.get_secret_value(),  # type: ignore[union-attr]
    )
    app.state.metadata = CinemetaClient(
        base_url=str(settings.cinemeta_base_url),
        metadata_ttl_seconds=settings.metadata_cache_ttl_seconds,
    )
    app.state.cache = CandidateCache(settings.database_path)
    app.state.search_locks = MediaSearchLocks()
    app.state.download_locks = MediaSearchLocks()
    app.state.monitor_health = MonitorHealth()
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.metrics = MetricsRegistry()
    app.state.event_monitor = asyncio.create_task(
        monitor_events(app.state.amule_api, app.state.cache, health=app.state.monitor_health),
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


def _observability_route(path: str) -> str:
    if path.startswith("/play/"):
        return "/play/{token}"
    if path.startswith("/file/"):
        return "/file/{token}"
    if path.endswith("/manifest.json"):
        return "/{installation_token}/manifest.json"
    if "/stream/" in path:
        return "/{installation_token}/stream/{media_type}/{media_id}.json"
    return path if path in {"/", "/configure", "/health", "/metrics"} else "/unknown"


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    started_at = time.perf_counter()
    route = _observability_route(request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        duration = time.perf_counter() - started_at
        _metrics(request).observe_request(
            method=request.method, route=route, status_code=500, duration=duration
        )
        logger.exception(
            "http_request_failed method=%s route=%s status=500 duration_ms=%.1f",
            request.method,
            route,
            duration * 1000,
        )
        raise
    duration = time.perf_counter() - started_at
    _metrics(request).observe_request(
        method=request.method, route=route, status_code=response.status_code, duration=duration
    )
    logger.info(
        "http_request method=%s route=%s status=%s duration_ms=%.1f",
        request.method,
        route,
        response.status_code,
        duration * 1000,
    )
    return response


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _metrics(request: Request) -> MetricsRegistry:
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is None:
        metrics = request.app.state.metrics = MetricsRegistry()
    return metrics


def _require_install_token(token: str, settings: Settings) -> None:
    if token != settings.install_token.get_secret_value():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


async def _enforce_rate_limit(
    request: Request, *, route: str, subject: str, limit: int, settings: Settings
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"{route}:{subject}:{client_ip}"
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        limiter = request.app.state.rate_limiter = SlidingWindowRateLimiter()
    if not await limiter.allow(key, limit=limit, window_seconds=settings.rate_limit_window_seconds):
        raise HTTPException(status_code=429, detail="Too many requests")


def _state_marker(state: str | None) -> str:
    if state == "ready":
        return "✅"
    if state == "downloading":
        return "⬇️"
    return "🧲"


def _download_details(file_state: FileState | None) -> str:
    if file_state is None or file_state.state != "downloading":
        return ""
    details: list[str] = []
    if file_state.percent is not None:
        details.append(f"⬇️ {file_state.percent:.1f}%")
    if file_state.speed_bps:
        details.append(f"⚡ {file_state.speed_bps / 1_000_000:.2f} MB/s")
    if file_state.sources_total is not None:
        details.append(f"👥 {file_state.sources_total} fuentes activas")
    return f"\n{' · '.join(details)}" if details else "\n⬇️ Descargando en aMule"


def _format_size(size: int) -> str:
    if size < 1_000_000:
        return f"{size / 1_000:.1f} KB"
    if size < 1_000_000_000:
        return f"{size / 1_000_000:.1f} MB"
    return f"{size / 1_000_000_000:.2f} GB"


def _stream_object(
    candidate: Candidate, request: Request, *, file_state: FileState | None = None
) -> dict:
    settings = _settings(request)
    token = sign(
        {"candidate": candidate.model_dump()},
        secret=settings.token_secret.get_secret_value(),
        ttl_seconds=settings.candidate_ttl_seconds,
    )
    is_local = candidate.local_path is not None
    if is_local:
        description = (
            f"Archivo local completado\n💾 {_format_size(candidate.size)} · {candidate.name}"
        )
    else:
        description = (
            f"{candidate.name}\n"
            f"💾 {_format_size(candidate.size)} · "
            f"👥 {candidate.sources_total} fuentes "
            f"({candidate.sources_complete} completas)"
            f"{_download_details(file_state)}"
        )
    stream_state = "ready" if is_local else file_state.state if file_state else None
    return {
        "name": (f"{_state_marker(stream_state)} aMulio · {candidate.quality or 'video'}"),
        "description": description,
        "url": f"{str(settings.public_url).rstrip('/')}/play/{token}",
        "behaviorHints": {
            "filename": candidate.name,
            "videoSize": candidate.size,
            # Completed local media is served as ordinary HTTPS byte ranges and
            # can be played by Stremio Web. Pending P2P downloads cannot.
            "notWebReady": candidate.local_path is None,
            "bingeGroup": f"amulio|{candidate.hash}",
        },
    }


def _stream_response(candidates: list[Candidate], request: Request, cache: CandidateCache) -> dict:
    states = cache.file_state_details([candidate.hash for candidate in candidates])
    return {
        "streams": [
            _stream_object(candidate, request, file_state=states.get(candidate.hash))
            for candidate in candidates
        ]
    }


def _safe_media_path(file_path: str, *, settings: Settings) -> Path:
    try:
        resolved_path = Path(file_path).resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The aMule media file is unavailable") from None
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


async def _queue_or_resolve_download(candidate: Candidate, api: AmuleApiClient):
    shared = await api.shared_file(candidate.hash)
    if shared:
        return shared, False
    existing_download = await api.download(candidate.hash)
    if existing_download and existing_download.status == "completed":
        return existing_download, False
    if existing_download is None:
        await api.add_download(candidate.ed2k_link)
        return None, True
    return None, False


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

        search_ids: tuple[int, ...] = ()
        try:
            async with asyncio.timeout(settings.search_timeout_seconds):
                resolved = await metadata.resolve(media_type, media_id)
                local_candidates = discover_local_media(resolved, settings)
                if local_candidates:
                    cache.put(
                        media_key, local_candidates, ttl_seconds=settings.candidate_ttl_seconds
                    )
                    return local_candidates
                queries = resolved.search_queries(
                    preferred_languages=settings.search_languages,
                    limit=settings.search_query_limit,
                )
                search_ids = tuple(
                    await asyncio.gather(
                        *(
                            api.start_search(query, kind=kind)
                            for query in queries
                            for kind in ("global", "kad")
                        )
                    )
                )
                await asyncio.sleep(settings.search_wait_seconds)
                result_sets = await asyncio.gather(
                    *(api.search_results(search_id) for search_id in search_ids)
                )
        except TimeoutError as exc:
            raise AmuleApiError("aMule search timed out") from exc
        finally:
            cleanup_results = await asyncio.gather(
                *(api.stop_search(search_id, close=True) for search_id in search_ids),
                return_exceptions=True,
            )
            for search_id, cleanup_result in zip(search_ids, cleanup_results, strict=True):
                if isinstance(cleanup_result, Exception):
                    logger.warning("Could not close aMule search %s: %s", search_id, cleanup_result)
        candidates = rank_results(
            [result for result_set in result_sets for result in result_set],
            resolved,
            allowed_extensions=settings.allowed_extensions,
            denied_extensions=settings.denied_extensions,
            allow_season_packs=settings.allow_season_packs,
            preferred_languages=settings.search_languages,
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
async def health(request: Request, api: ApiClient):
    try:
        return {
            "ok": True,
            "amule": await api.health(),
            "events": request.app.state.monitor_health.as_dict(),
        }
    except AmuleApiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    settings = _settings(request)
    if settings.metrics_token is None:
        raise HTTPException(status_code=404)
    authorization = request.headers.get("Authorization")
    expected = f"Bearer {settings.metrics_token.get_secret_value()}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=404)
    return PlainTextResponse(
        _metrics(request).render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/configure")


@app.get("/configure", response_class=HTMLResponse)
async def configure(request: Request):
    return _configuration_page(_settings(request))


@app.get("/{installation_token}/configure", response_class=HTMLResponse)
async def tokenized_configure(installation_token: str, request: Request):
    """Serve Stremio's configuration URL, which is relative to the manifest."""
    settings = _settings(request)
    _require_install_token(installation_token, settings)
    return _configuration_page(settings)


def _configuration_page(settings: Settings) -> str:
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
    await _enforce_rate_limit(
        request,
        route="manifest",
        subject=installation_token,
        limit=settings.manifest_rate_limit,
        settings=settings,
    )
    return {
        "id": "com.alexruperez.amulio",
        "version": "0.1.0",
        "name": "aMulio",
        "description": "Busca contenido eD2K/Kad y reproduce archivos completados de aMule.",
        "catalogs": [],
        "resources": [{"name": "stream", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
        "types": ["movie", "series"],
        # This initial release has no per-user options.  Declaring it configurable
        # would make Stremio route users to ``/<token>/configure`` indefinitely.
        "behaviorHints": {"p2p": True},
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
    await _enforce_rate_limit(
        request,
        route="stream",
        subject=installation_token,
        limit=settings.stream_rate_limit,
        settings=settings,
    )
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
async def play(token: str, request: Request, api: ApiClient, cache: Cache):
    settings = _settings(request)
    await _enforce_rate_limit(
        request,
        route="playback",
        subject=token,
        limit=settings.playback_rate_limit,
        settings=settings,
    )
    try:
        candidate = Candidate.model_validate(
            verify(token, secret=settings.token_secret.get_secret_value())["candidate"]
        )
    except (InvalidToken, KeyError):
        raise HTTPException(status_code=404) from None

    if candidate.local_path is not None:
        _safe_media_path(candidate.local_path, settings=settings)
        return RedirectResponse(f"/file/{token}", status_code=307)

    queued = False
    try:
        async with request.app.state.download_locks.acquire(f"download:{candidate.hash}"):
            completed, queued = await _queue_or_resolve_download(candidate, api)
            if completed:
                return RedirectResponse(f"/file/{token}", status_code=307)
            if queued:
                cache.set_file_state(candidate.hash, "downloading", status="queued")
    except AmuleApiError as exc:
        logger.warning("aMule is unavailable while playing %s: %s", candidate.hash, exc)
        return status_video("unavailable")

    if queued:
        return status_video("started")
    file_state = cache.file_state(candidate.hash)
    return status_video(
        "downloading" if file_state and file_state.state == "downloading" else "started"
    )


@app.api_route("/file/{token}", methods=["GET", "HEAD"])
async def file(token: str, request: Request, api: ApiClient):
    settings = _settings(request)
    await _enforce_rate_limit(
        request,
        route="playback",
        subject=token,
        limit=settings.playback_rate_limit,
        settings=settings,
    )
    try:
        candidate = Candidate.model_validate(
            verify(token, secret=settings.token_secret.get_secret_value())["candidate"]
        )
    except (InvalidToken, KeyError):
        raise HTTPException(status_code=404) from None

    if candidate.local_path is not None:
        path = _safe_media_path(candidate.local_path, settings=settings)
        if path.name != candidate.name or path.stat().st_size != candidate.size:
            raise HTTPException(
                status_code=409, detail="The completed file no longer matches this stream"
            )
        return FileResponse(path, filename=candidate.name, content_disposition_type="inline")

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
