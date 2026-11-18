# ruff: noqa: E501
# The embedded configuration page deliberately retains readable, browser-oriented
# HTML and CSS rather than making the application depend on a templating stack.

import asyncio
import html
import ipaddress
import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, SecretStr

from amulio.amule_api import AmuleApiClient, AmuleApiError
from amulio.cache import CandidateCache, FileState
from amulio.config import Settings, get_settings
from amulio.download_manager import (
    normalize_hashes,
    public_download,
    public_shared_file,
    require_active_selection,
)
from amulio.events import MonitorHealth, monitor_events, stop_monitor
from amulio.i18n import Locale, resolve_locale, translate
from amulio.local_media import discover_local_media
from amulio.metadata import CinemetaClient, MetadataError
from amulio.models import Candidate
from amulio.observability import MetricsRegistry, configure_logging
from amulio.profiles import AddonProfile, ProfilePreferences, ProfileStore
from amulio.ranking import rank_results
from amulio.rate_limit import SlidingWindowRateLimiter
from amulio.search_locks import MediaSearchLocks
from amulio.status_videos import StatusVideoKind, status_video, status_video_filename
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


def _get_profile_store(request: Request) -> ProfileStore:
    return request.app.state.profile_store


Profiles = Annotated[ProfileStore, Depends(_get_profile_store)]


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
    app.state.profile_store = ProfileStore(settings.database_path)
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
    app.state.profile_store.close()


ASSET_DIRECTORY = Path(__file__).with_name("assets")
AMULE_LOGO_VERSION = "ba6013323359a1fa28a932b2acef5f65b709923a298c4fa9fc5379a1a46b80e4"

app = FastAPI(title="aMulio", version="0.1.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=ASSET_DIRECTORY), name="assets")
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
    if path.endswith("/configure/status"):
        return "/{installation_token}/configure/status"
    if "/stream/" in path:
        return "/{installation_token}/stream/{media_type}/{media_id}.json"
    if path.startswith("/assets/"):
        return "/assets/{asset}"
    if path.startswith("/admin/"):
        return "/admin/{route}"
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


def _require_admin_session(request: Request) -> dict:
    """Return a verified admin session without accepting Stremio capabilities."""
    settings = _settings(request)
    session_token = request.cookies.get("amulio_admin")
    if session_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        payload = verify(session_token, secret=settings.token_secret.get_secret_value())
    except InvalidToken as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc
    if payload.get("scope") != "admin" or not isinstance(payload.get("csrf"), str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return payload


def _trusted_ingress_user(request: Request, settings: Settings) -> str | None:
    """Accept a Supervisor identity header only from an explicitly trusted peer."""
    user_id = request.headers.get("X-Remote-User-ID", "").strip()
    if not user_id or not _is_trusted_ingress_proxy(request, settings):
        return None
    return user_id


def _is_trusted_ingress_proxy(request: Request, settings: Settings) -> bool:
    """Return whether the TCP peer is an explicitly configured Ingress proxy."""
    client_host = request.client.host if request.client else ""
    if not client_host:
        return False
    try:
        client_address = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    return any(client_address in network for network in settings.trusted_ingress_proxies)


def _trusted_ingress_path(request: Request, settings: Settings) -> str | None:
    """Return a validated external app prefix from a trusted Supervisor proxy."""
    if not _is_trusted_ingress_proxy(request, settings):
        return None
    value = request.headers.get("X-Ingress-Path", "")
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if (
        not value
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or value != parsed.path
        or not path.startswith("/")
        or path.startswith("//")
        or unquote(path) != path
        or any(segment in {"", ".", ".."} for segment in path.split("/")[1:])
    ):
        return None
    return path


def _require_csrf(request: Request) -> None:
    payload = _require_admin_session(request)
    csrf_token = request.headers.get("X-CSRF-Token")
    if csrf_token is None or not secrets.compare_digest(csrf_token, payload["csrf"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


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


def _state_marker(state: str) -> str:
    if state == "ready":
        return "✅"
    if state == "downloading":
        return "⬇️"
    return "🧲"


def _download_details(
    file_state: FileState | None,
    *,
    locale: Locale = "en",
    show_sources: bool = True,
) -> str:
    if file_state is None or file_state.state != "downloading":
        return ""
    details: list[str] = []
    if file_state.percent is not None:
        details.append(f"⬇️ {file_state.percent:.1f}%")
    if file_state.speed_bps:
        details.append(f"⚡ {file_state.speed_bps / 1_000_000:.2f} MB/s")
    if show_sources and file_state.sources_total is not None:
        details.append(
            f"👥 {translate(locale, 'stream_known_sources').format(count=file_state.sources_total)}"
        )
    return f"\n{' · '.join(details)}" if details else ""


def _format_size(size: int) -> str:
    if size < 1_000_000:
        return f"{size / 1_000:.1f} KB"
    if size < 1_000_000_000:
        return f"{size / 1_000_000:.1f} MB"
    return f"{size / 1_000_000_000:.2f} GB"


def _default_preferences(settings: Settings) -> ProfilePreferences:
    """Return the node-wide defaults used by the base installation manifest."""
    return ProfilePreferences(
        search_languages=settings.search_languages,
        allow_season_packs=settings.allow_season_packs,
        result_limit=settings.default_result_limit,
        max_size_gb=settings.default_max_size_gb or None,
        show_stream_size=settings.default_show_stream_size,
        show_stream_sources=settings.default_show_stream_sources,
        show_stream_language=settings.default_show_stream_language,
        show_stream_technical_details=settings.default_show_stream_technical_details,
    )


def _stream_facts(
    candidate: Candidate,
    *,
    preferences: ProfilePreferences,
    locale: Locale,
) -> list[str]:
    """Return only file facts that the addon knows and the profile requested."""
    primary: list[str] = []
    if preferences.show_stream_size:
        primary.append(f"💾 {_format_size(candidate.size)}")
    if preferences.show_stream_sources and candidate.sources_total:
        primary.append(
            f"👥 {translate(locale, 'stream_sources').format(count=candidate.sources_total)}"
        )

    secondary: list[str] = []
    if preferences.show_stream_technical_details:
        technical = [
            value for value in (candidate.codec, "HDR" if candidate.hdr else None) if value
        ]
        if technical:
            secondary.append(f"🎞️ {' · '.join(technical)}")
        if candidate.release_group:
            secondary.append(f"⚙️ {candidate.release_group}")
    if preferences.show_stream_language and candidate.language:
        secondary.append(f"🌐 {candidate.language.upper()}")

    lines = [" · ".join(primary)] if primary else []
    if secondary:
        lines.append(" · ".join(secondary))
    return lines


def _stream_object(
    candidate: Candidate,
    request: Request,
    *,
    file_state: FileState | None = None,
    locale: Locale = "en",
    preferences: ProfilePreferences | None = None,
) -> dict:
    settings = _settings(request)
    token = sign(
        {"candidate": candidate.model_dump(), "locale": locale},
        secret=settings.token_secret.get_secret_value(),
        ttl_seconds=settings.candidate_ttl_seconds,
    )
    is_local = candidate.local_path is not None
    stream_state = (
        "ready"
        if is_local
        else "downloading"
        if file_state is not None and file_state.state == "downloading"
        else "download"
    )
    display_preferences = preferences or _default_preferences(settings)
    stream_label = translate(
        locale,
        {
            "ready": "stream_ready",
            "downloading": "stream_downloading",
            "download": "stream_download",
        }[stream_state],
    )
    quality = candidate.quality or translate(locale, "stream_quality_fallback")
    details = _stream_facts(candidate, preferences=display_preferences, locale=locale)
    if stream_state == "downloading":
        details.append(
            _download_details(
                file_state,
                locale=locale,
                show_sources=display_preferences.show_stream_sources
                and not bool(candidate.sources_total),
            ).lstrip("\n")
        )
    description = "\n".join([candidate.name, *(detail for detail in details if detail)])
    return {
        "name": f"{_state_marker(stream_state)} {stream_label} · {quality}",
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


def _status_stream(
    settings: Settings, *, kind: StatusVideoKind, label: str, detail: str, locale: Locale = "en"
) -> dict:
    return {
        "name": f"ℹ️ aMulio · {label}",
        "description": detail,
        "url": (
            f"{str(settings.public_url).rstrip('/')}/assets/"
            f"{status_video_filename(kind, locale=locale)}"
        ),
        "behaviorHints": {"notWebReady": False},
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
    preferences: ProfilePreferences | None = None,
    cache_scope: str = "default",
) -> list[Candidate]:
    # Stremio uses tt<id>:<season>:<episode> for episodes, making this key
    # independently serialise every movie and episode lookup.
    media_key = f"{media_type}:{media_id}:{cache_scope}"
    fixture = _e2e_fixture_candidate(media_type, media_id, settings)
    if fixture is not None:
        return [fixture]
    effective_preferences = preferences or _default_preferences(settings)
    preferred_languages = effective_preferences.search_languages
    allow_season_packs = effective_preferences.allow_season_packs
    result_limit = effective_preferences.result_limit
    max_size_bytes = (
        int(effective_preferences.max_size_gb * 1_000_000_000)
        if effective_preferences.max_size_gb is not None
        else None
    )
    cached = cache.get(media_key)
    if cached is not None:
        if _cached_candidates_are_available(cached):
            return cached
        cache.delete(media_key)

    async with search_locks.acquire(media_key):
        # A request that waited for an identical search should reuse its result.
        cached = cache.get(media_key)
        if cached is not None:
            if _cached_candidates_are_available(cached):
                return cached
            cache.delete(media_key)

        search_ids: tuple[int, ...] = ()
        try:
            async with asyncio.timeout(settings.search_timeout_seconds):
                resolved = await metadata.resolve(media_type, media_id)
                local_candidates = discover_local_media(
                    resolved,
                    settings,
                    allow_season_packs=allow_season_packs,
                    preferred_languages=preferred_languages,
                )
                if local_candidates:
                    local_candidates = _apply_profile_limits(
                        local_candidates, result_limit=result_limit, max_size_bytes=max_size_bytes
                    )
                    cache.put(
                        media_key, local_candidates, ttl_seconds=settings.candidate_ttl_seconds
                    )
                    return local_candidates
                queries = resolved.search_queries(
                    preferred_languages=preferred_languages,
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
            allow_season_packs=allow_season_packs,
            preferred_languages=preferred_languages,
        )
        candidates = _apply_profile_limits(
            candidates, result_limit=result_limit, max_size_bytes=max_size_bytes
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


def _e2e_fixture_candidate(media_type: str, media_id: str, settings: Settings) -> Candidate | None:
    """Return an explicitly configured private eD2K test fixture, if applicable."""
    if media_type != "movie" or media_id != settings.e2e_fixture_media_id:
        return None
    link = settings.e2e_fixture_ed2k_link
    if not link:
        return None
    match = re.fullmatch(
        r"ed2k://\|file\|([^|]+)\|(\d+)\|([0-9a-fA-F]{32})\|/(?:\|sources,[^|]+\|/)?",
        link,
    )
    if match is None:
        logger.warning("Ignoring malformed AMULIO_E2E_FIXTURE_ED2K_LINK")
        return None
    name, size, file_hash = match.groups()
    return Candidate(
        name=unquote(name),
        size=int(size),
        hash=file_hash.lower(),
        ed2k_link=link,
        sources_total=1,
        sources_complete=1,
        release_group="E2E",
        score=10_000,
    )


def _cached_candidates_are_available(candidates: list[Candidate]) -> bool:
    """Do not serve expired local file paths from the persistent stream cache."""
    return all(
        candidate.local_path is None or Path(candidate.local_path).is_file()
        for candidate in candidates
    )


def _apply_profile_limits(
    candidates: list[Candidate], *, result_limit: int, max_size_bytes: int | None
) -> list[Candidate]:
    if max_size_bytes is not None:
        candidates = [candidate for candidate in candidates if candidate.size <= max_size_bytes]
    return candidates[:result_limit]


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
    # Keep this relative so Home Assistant Ingress retains its per-app prefix.
    # An absolute `/configure` escapes the Ingress URL and opens a blank Core
    # route instead of aMulio's configuration page.
    return RedirectResponse("configure")


@app.get("/configure", response_class=HTMLResponse)
async def configure(request: Request):
    settings = _settings(request)
    ingress_sso = (
        _trusted_ingress_user(request, settings) is not None
        and _trusted_ingress_path(request, settings) is not None
    )
    return _configuration_page(
        settings,
        resolve_locale(request.query_params.get("lang")),
        ingress_sso=ingress_sso,
    )


@app.get("/{installation_token}/configure", response_class=HTMLResponse)
async def tokenized_configure(installation_token: str, request: Request):
    """Serve Stremio's configuration URL, which is relative to the manifest."""
    settings = _settings(request)
    _require_install_token(installation_token, settings)
    return _configuration_page(settings, resolve_locale(request.query_params.get("lang")))


def _connection_state(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    state = value.get("state")
    return state if state in {"connected", "connecting", "disconnected"} else "unknown"


@app.get("/{installation_token}/configure/status")
async def configuration_status(installation_token: str, request: Request, api: ApiClient):
    """Return non-sensitive readiness data for the private install page."""
    settings = _settings(request)
    _require_install_token(installation_token, settings)
    return await _configuration_status(settings, api)


@app.get("/configure/status")
async def ingress_configuration_status(request: Request, api: ApiClient):
    """Return readiness data only to the trusted Supervisor Ingress proxy."""
    settings = _settings(request)
    if (
        _trusted_ingress_user(request, settings) is None
        or _trusted_ingress_path(request, settings) is None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return await _configuration_status(settings, api)


async def _configuration_status(settings: Settings, api: ApiClient) -> Response:
    storage_ready = bool(settings.media_roots) and all(
        Path(media_root).is_dir() for media_root in settings.media_roots
    )
    try:
        amule_status = await api.health()
    except AmuleApiError:
        amule_status = {}
    response = {
        "amuleapi": "connected" if amule_status else "unavailable",
        "ed2k": _connection_state(amule_status.get("ed2k")),
        "kad": _connection_state(amule_status.get("kad")),
        # Home Assistant owns port publication. The core cannot inspect the
        # effective host mapping or router/NAT state, so do not make a claim.
        "peer_access": "unknown",
        "incoming_storage": "ready" if storage_ready else "unavailable",
        "public_url": "configured",
    }
    return Response(
        content=json.dumps(response),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


class AdminLoginRequest(BaseModel):
    password: SecretStr


class AdminBootstrapRequest(BaseModel):
    token: SecretStr


class AdminSessionResponse(BaseModel):
    csrf_token: str
    expires_in_seconds: int


def _establish_admin_session(
    response: Response, settings: Settings, *, cookie_path: str = "/admin"
) -> AdminSessionResponse:
    """Set an HttpOnly, CSRF-bound administrative session after authentication."""
    csrf_token = secrets.token_urlsafe(32)
    session_token = sign(
        {"scope": "admin", "csrf": csrf_token},
        secret=settings.token_secret.get_secret_value(),
        ttl_seconds=settings.admin_session_ttl_seconds,
    )
    response.set_cookie(
        "amulio_admin",
        session_token,
        max_age=settings.admin_session_ttl_seconds,
        httponly=True,
        secure=str(settings.public_url).startswith("https://"),
        samesite="strict",
        path=cookie_path,
    )
    response.headers["Cache-Control"] = "no-store"
    return AdminSessionResponse(
        csrf_token=csrf_token, expires_in_seconds=settings.admin_session_ttl_seconds
    )


class DownloadSelectionRequest(BaseModel):
    hashes: list[str]

    def normalized_hashes(self) -> list[str]:
        try:
            return normalize_hashes(self.hashes)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc


class DownloadStatusRequest(DownloadSelectionRequest):
    action: str


class DownloadCancelRequest(DownloadSelectionRequest):
    confirmation: str


class ProfileInstallationResponse(BaseModel):
    manifest_url: str


@app.post("/admin/session", response_model=AdminSessionResponse)
async def create_admin_session(
    credentials: AdminLoginRequest, request: Request, response: Response
) -> AdminSessionResponse:
    """Create an HttpOnly administrative session when it is explicitly enabled."""
    settings = _settings(request)
    if settings.admin_password is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await _enforce_rate_limit(
        request,
        route="admin-login",
        subject="admin",
        limit=settings.admin_login_rate_limit,
        settings=settings,
    )
    if not secrets.compare_digest(
        credentials.password.get_secret_value(), settings.admin_password.get_secret_value()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return _establish_admin_session(response, settings)


@app.post("/admin/bootstrap", response_model=AdminSessionResponse)
async def bootstrap_admin_session(
    credentials: AdminBootstrapRequest, request: Request, response: Response
) -> AdminSessionResponse:
    """Bootstrap an admin session from an operator-supplied secret."""
    settings = _settings(request)
    if settings.admin_password is None or settings.admin_bootstrap_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await _enforce_rate_limit(
        request,
        route="admin-bootstrap",
        subject="admin",
        limit=settings.admin_bootstrap_rate_limit,
        settings=settings,
    )
    if not secrets.compare_digest(
        credentials.token.get_secret_value(), settings.admin_bootstrap_token.get_secret_value()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return _establish_admin_session(response, settings)


@app.post("/admin/ingress-session", response_model=AdminSessionResponse)
async def ingress_admin_session(request: Request, response: Response) -> AdminSessionResponse:
    """Bootstrap only from a Supervisor proxy explicitly trusted by the operator."""
    settings = _settings(request)
    ingress_path = _trusted_ingress_path(request, settings)
    if _trusted_ingress_user(request, settings) is None or ingress_path is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return _establish_admin_session(response, settings, cookie_path=f"{ingress_path}/admin")


@app.delete("/admin/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_session(request: Request, response: Response) -> None:
    _require_csrf(request)
    settings = _settings(request)
    ingress_path = _trusted_ingress_path(request, settings)
    response.delete_cookie(
        "amulio_admin",
        path=f"{ingress_path}/admin" if ingress_path is not None else "/admin",
        httponly=True,
        samesite="strict",
    )


@app.get("/admin/downloads")
async def managed_downloads(request: Request, api: ApiClient):
    """List queue and shared library for a verified administrator only."""
    _require_admin_session(request)
    try:
        downloads, shared = await asyncio.gather(api.downloads(), api.shared_files())
        return {
            "downloads": [
                public_download(item) for item in downloads if item.get("status") != "completed"
            ],
            "shared": [public_shared_file(item) for item in shared],
        }
    except (AmuleApiError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="aMule queue is unavailable") from exc


@app.patch("/admin/downloads")
async def manage_download_status(body: DownloadStatusRequest, request: Request, api: ApiClient):
    _require_csrf(request)
    hashes = body.normalized_hashes()
    if body.action not in {"pause", "resume"}:
        raise HTTPException(status_code=422, detail="action must be pause or resume")
    try:
        downloads = await api.downloads()
        require_active_selection(hashes, downloads)
        results = (
            await api.pause_downloads(hashes)
            if body.action == "pause"
            else await api.resume_downloads(hashes)
        )
    except AmuleApiError as exc:
        raise HTTPException(status_code=503, detail="aMule queue update failed") from exc
    return {"results": results}


@app.delete("/admin/downloads")
async def cancel_managed_downloads(body: DownloadCancelRequest, request: Request, api: ApiClient):
    """Cancel only active aMule partfiles; completed shared files are never deleted."""
    _require_csrf(request)
    hashes = body.normalized_hashes()
    if not secrets.compare_digest(body.confirmation, f"CANCELAR {len(hashes)}"):
        raise HTTPException(status_code=422, detail="Type the exact cancellation confirmation")
    try:
        downloads = await api.downloads()
        require_active_selection(hashes, downloads)
        return {"results": await api.cancel_downloads(hashes)}
    except AmuleApiError as exc:
        raise HTTPException(status_code=503, detail="aMule cancellation failed") from exc


@app.post("/admin/profiles", response_model=AddonProfile, status_code=status.HTTP_201_CREATED)
async def create_profile(
    request: Request, profiles: Profiles, preferences: ProfilePreferences | None = None
) -> AddonProfile:
    _require_csrf(request)
    return profiles.create(preferences)


@app.get("/admin/profiles/{profile_id}", response_model=AddonProfile)
async def get_profile(profile_id: str, request: Request, profiles: Profiles) -> AddonProfile:
    _require_admin_session(request)
    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return profile


@app.get("/admin/profiles/{profile_id}/installation", response_model=ProfileInstallationResponse)
async def profile_installation_url(
    profile_id: str, request: Request, profiles: Profiles
) -> ProfileInstallationResponse:
    _require_admin_session(request)
    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ProfileInstallationResponse(
        manifest_url=_profile_manifest_url(_settings(request), profile)
    )


@app.put("/admin/profiles/{profile_id}", response_model=AddonProfile)
async def update_profile(
    profile_id: str, preferences: ProfilePreferences, request: Request, profiles: Profiles
) -> AddonProfile:
    _require_csrf(request)
    profile = profiles.update(profile_id, preferences)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return profile


@app.post("/admin/profiles/{profile_id}/rotate", response_model=AddonProfile)
async def rotate_profile(profile_id: str, request: Request, profiles: Profiles) -> AddonProfile:
    _require_csrf(request)
    profile = profiles.rotate(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return profile


@app.delete("/admin/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_profile(profile_id: str, request: Request, profiles: Profiles) -> None:
    _require_csrf(request)
    if not profiles.revoke(profile_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _configuration_page(
    settings: Settings, locale: Locale = "en", *, ingress_sso: bool = False
) -> str:
    manifest_url = (
        f"{str(settings.public_url).rstrip('/')}/"
        f"{settings.install_token.get_secret_value()}/manifest.json"
    )
    safe_manifest_url = html.escape(manifest_url)
    stremio_url = html.escape(
        "stremio://" + manifest_url.removeprefix("https://").removeprefix("http://")
    )
    status_url = (
        "configure/status"
        if ingress_sso
        else (
            f"{str(settings.public_url).rstrip('/')}/"
            f"{settings.install_token.get_secret_value()}/configure/status"
        )
    )
    status_url = html.escape(status_url)
    # Keep this relative so Home Assistant Ingress retains its private app prefix.
    logo_url = html.escape(f"assets/amule-logo.png?v={AMULE_LOGO_VERSION}")
    profile_management_enabled = settings.admin_password is not None and not ingress_sso
    profile_disabled = " disabled" if not profile_management_enabled else ""
    profile_hidden = " hidden" if not profile_management_enabled else ""
    manager_hidden = " hidden" if settings.admin_password is None and not ingress_sso else ""

    def t(key: str) -> str:
        return html.escape(translate(locale, key))

    manager_auth = (
        f"<p>{t('manager_ingress_auth')}</p>"
        f'<div class="actions"><button class="button" type="button" id="manager-load">{t("manager_open")}</button></div>'
        if ingress_sso
        else f'<label for="manager-password">{t("admin_password")}'
        '<input id="manager-password" type="password" autocomplete="current-password"'
        f'{profile_disabled}></label><div class="actions"><button class="button" type="button" id="manager-load"{profile_disabled}>{t("manager_load")}</button></div>'
    )
    bootstrap_action = (
        f"""
            <div id="manager-bootstrap">
              <p>{t("manager_bootstrap_intro")}</p>
              <div class="actions">
                <button class="button secondary" type="button" id="manager-bootstrap-open">{t("manager_bootstrap_open")}</button>
                <button class="button secondary" type="button" id="manager-bootstrap-copy">{t("manager_bootstrap_copy")}</button>
              </div>
            </div>"""
        if settings.admin_password is not None
        and settings.admin_bootstrap_token is not None
        and not ingress_sso
        else ""
    )

    status_labels = json.dumps(
        {
            key: translate(locale, key)
            for key in (
                "connected",
                "connecting",
                "disconnected",
                "ready",
                "configured",
                "limited",
                "unavailable",
                "unknown",
            )
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
    manager_messages = json.dumps(
        {
            key: translate(locale, key)
            for key in (
                "manager_connected",
                "manager_bootstrap_missing",
                "manager_bootstrap_copied",
                "manager_bootstrap_copy_failed",
                "manager_refresh",
                "manager_loading",
                "manager_loaded",
                "manager_load_failed",
                "manager_empty",
                "manager_selected",
                "manager_pause",
                "manager_resume",
                "manager_cancel",
                "manager_cancel_title",
                "manager_cancel_warning",
                "manager_cancel_prompt",
                "manager_cancel_confirm",
                "manager_cancel_failed",
                "manager_update_failed",
                "manager_library_empty",
                "manager_file_details",
                "manager_network_unavailable",
                "manager_peers",
                "manager_pause_completed",
                "manager_resume_completed",
                "manager_cancel_completed",
            )
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
    language_links = " ".join(
        '<a href="?lang={language}"{current}>{label}</a>'.format(
            language=language,
            current=' aria-current="page"' if language == locale else "",
            label=t("english" if language == "en" else "spanish"),
        )
        for language in ("en", "es")
    )
    # The manager is an Ingress-only administrative surface.
    manager_section = (
        f"""\
        <details class="manager-settings" id="download-manager"{manager_hidden}>
          <summary><span class="manager-title">{t("manager_title")}</span><span class="manager-subtitle">{t("manager_subtitle")}</span></summary>
          <div class="profile-content">
            <p class="manager-intro">{t("manager_intro")}</p>
            {bootstrap_action}
            <div id="manager-auth">{manager_auth}</div>
            <div id="manager-session" class="manager-session" hidden>
              <strong>{t("manager_connected")}</strong><button class="button secondary" type="button" id="manager-refresh">{t("manager_refresh")}</button>
            </div>
            <div id="manager-feedback" class="profile-feedback manager-feedback" role="status" aria-live="polite"></div>
            <section id="manager-content" hidden>
              <div id="manager-downloads"></div>
              <div id="manager-toolbar" class="manager-toolbar" hidden>
                <span id="manager-selection-count" class="manager-selection-count"></span>
                <div class="actions">
                  <button class="button secondary" type="button" data-manager-action="pause" disabled>{t("manager_pause")}</button>
                  <button class="button secondary" type="button" data-manager-action="resume" disabled>{t("manager_resume")}</button>
                  <button class="button destructive" type="button" id="manager-cancel-open" data-destructive="true" disabled></button>
                </div>
                <section id="manager-cancel-panel" class="manager-cancel-panel" hidden aria-labelledby="manager-cancel-title">
                  <h4 id="manager-cancel-title"></h4><p id="manager-cancel-warning"></p>
                  <label id="manager-cancel-prompt" for="manager-confirmation"></label>
                  <input id="manager-confirmation" type="text" autocomplete="off">
                  <button class="button destructive" type="button" id="manager-cancel-confirm" data-destructive="true" disabled></button>
                </section>
              </div>
              <details class="manager-network" id="manager-network">
                <summary>{t("manager_network")}</summary>
                <div class="manager-network-body">
                  <div id="manager-network-states" class="manager-network-states"></div>
                  <p>{t("manager_network_hint")}</p>
                </div>
              </details>
              <h3>{t("manager_library")}</h3><div id="manager-shared"></div>
            </section>
          </div>
        </details>
    """
        if ingress_sso
        else ""
    )

    manager_script = (
        f"""\
      const managerLoad = document.getElementById("manager-load");
      const managerRefresh = document.getElementById("manager-refresh");
      const managerBootstrapOpen = document.getElementById("manager-bootstrap-open");
      const managerBootstrapCopy = document.getElementById("manager-bootstrap-copy");
      const managerPassword = document.getElementById("manager-password");
      const ingressSso = {str(ingress_sso).lower()};
      const managerMessages = {manager_messages};
      const managerFeedback = document.getElementById("manager-feedback");
      const managerAuth = document.getElementById("manager-auth");
      const managerSession = document.getElementById("manager-session");
      const managerContent = document.getElementById("manager-content");
      const managerDownloads = document.getElementById("manager-downloads");
      const managerShared = document.getElementById("manager-shared");
      const managerToolbar = document.getElementById("manager-toolbar");
      const managerSelectionCount = document.getElementById("manager-selection-count");
      const managerCancelOpen = document.getElementById("manager-cancel-open");
      const managerCancelPanel = document.getElementById("manager-cancel-panel");
      const managerCancelTitle = document.getElementById("manager-cancel-title");
      const managerCancelWarning = document.getElementById("manager-cancel-warning");
      const managerCancelPrompt = document.getElementById("manager-cancel-prompt");
      const managerCancelConfirm = document.getElementById("manager-cancel-confirm");
      const managerConfirmation = document.getElementById("manager-confirmation");
      const managerNetworkStates = document.getElementById("manager-network-states");
      let managerCsrf = null;
      let managerFeedbackTimer = null;
      // Ingress exposes the app under a per-session prefix. A parent-relative
      // URL would escape that prefix; direct and tokenized pages retain the
      // parent-relative API location.
      const managerApiBase = ingressSso ? "admin" : "../admin";
      const managerEscape = (value) => String(value).replace(/[&<>\"]/g, (c) => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '\"': "&quot;" }}[c]));
      const formatBytes = (value) => {{
        const bytes = Number(value);
        if (!Number.isFinite(bytes) || bytes < 0) return "—";
        const units = ["B", "KiB", "MiB", "GiB", "TiB"];
        let index = 0;
        let formatted = bytes;
        while (formatted >= 1024 && index < units.length - 1) {{ formatted /= 1024; index += 1; }}
        return `${{formatted.toLocaleString(undefined, {{ maximumFractionDigits: index ? 1 : 0 }})}} ${{units[index]}}`;
      }};
      const selectedDownloads = () => Array.from(managerDownloads.querySelectorAll(".manager-download:checked")).map((input) => input.value);
      const cancellationPhrase = () => `CANCELAR ${{selectedDownloads().length}}`;
      function setManagerFeedback(message, kind = "success", transient = true) {{
        window.clearTimeout(managerFeedbackTimer);
        managerFeedback.dataset.kind = kind;
        managerFeedback.textContent = message;
        if (transient && message) managerFeedbackTimer = window.setTimeout(() => {{ managerFeedback.textContent = ""; }}, 3200);
      }}
      function resetCancellation() {{
        managerCancelPanel.hidden = true;
        managerConfirmation.value = "";
        managerCancelConfirm.disabled = true;
      }}
      function updateManagerControls() {{
        const count = selectedDownloads().length;
        managerToolbar.hidden = !managerDownloads.querySelector(".manager-download");
        managerSelectionCount.textContent = managerMessages.manager_selected.replace("{{count}}", count);
        managerToolbar.querySelectorAll('[data-manager-action="pause"], [data-manager-action="resume"]').forEach((button) => {{ button.disabled = !count; }});
        managerCancelOpen.disabled = !count;
        managerCancelOpen.textContent = managerMessages.manager_cancel.replace("{{count}}", count);
        managerCancelTitle.textContent = managerMessages.manager_cancel_title;
        managerCancelWarning.textContent = managerMessages.manager_cancel_warning;
        managerCancelPrompt.textContent = managerMessages.manager_cancel_prompt.replace("{{confirmation}}", cancellationPhrase());
        resetCancellation();
      }}
      function renderManager(data) {{
        managerDownloads.innerHTML = data.downloads.length
          ? `<ul class="manager-download-list">${{data.downloads.map((item) => `<li class="manager-download-row"><label><input class="manager-download" type="checkbox" value="${{managerEscape(item.hash)}}"><span><span class="manager-download-name">${{managerEscape(item.name)}}</span><span class="manager-meta">${{managerEscape(item.status)}} · ${{formatBytes(item.size_done)}} / ${{formatBytes(item.size)}}</span></span></label></li>`).join("")}}</ul>`
          : `<p class="manager-empty">${{managerMessages.manager_empty}}</p>`;
        managerShared.innerHTML = data.shared.length
          ? `<ul class="manager-library-list">${{data.shared.map((item) => `<li class="manager-library-card"><span class="manager-library-name">${{managerEscape(item.name)}}</span><span class="manager-meta">${{formatBytes(item.size)}}</span><details><summary>${{managerMessages.manager_file_details}}</summary><code>${{managerEscape(item.name)}}</code></details></li>`).join("")}}</ul>`
          : `<p class="manager-library-empty">${{managerMessages.manager_library_empty}}</p>`;
        managerContent.hidden = false;
        updateManagerControls();
      }}
      function renderNetworkStatus(states) {{
        managerNetworkStates.innerHTML = ["ed2k", "kad", "peer_access"].map((key) => `<div class="manager-network-state">${{managerEscape(key === "peer_access" ? managerMessages.manager_peers : key === "ed2k" ? "eD2K" : "Kad")}}<strong>${{managerEscape(statusLabels[states[key]] || statusLabels.unknown)}}</strong></div>`).join("");
      }}
      async function loadManager() {{
        const response = await fetch(`${{managerApiBase}}/downloads`, {{ cache: "no-store" }});
        if (!response.ok) throw new Error("queue");
        renderManager(await response.json());
        try {{
          const network = await fetch(readiness.dataset.statusUrl, {{ cache: "no-store" }});
          if (!network.ok) throw new Error("network");
          renderNetworkStatus(await network.json());
        }} catch {{
          managerNetworkStates.innerHTML = `<p class="manager-library-empty">${{managerMessages.manager_network_unavailable}}</p>`;
        }}
      }}
      function bootstrapTokenFromFragment() {{
        return new URLSearchParams(window.location.hash.slice(1)).get("admin-bootstrap");
      }}
      managerBootstrapCopy?.addEventListener("click", async () => {{
        if (!bootstrapTokenFromFragment()) {{
          managerFeedback.dataset.kind = "error";
          managerFeedback.textContent = managerMessages.manager_bootstrap_missing;
          return;
        }}
        try {{
          await navigator.clipboard.writeText(window.location.href);
          managerFeedback.dataset.kind = "success";
          managerFeedback.textContent = managerMessages.manager_bootstrap_copied;
        }} catch {{
          managerFeedback.dataset.kind = "error";
          managerFeedback.textContent = managerMessages.manager_bootstrap_copy_failed;
        }}
      }});
      async function openManagerSession(login) {{
        managerCsrf = (await login.json()).csrf_token;
        if (managerPassword) managerPassword.value = "";
        await loadManager();
        managerAuth.hidden = true;
        document.getElementById("manager-bootstrap")?.setAttribute("hidden", "");
        managerSession.hidden = false;
        setManagerFeedback(managerMessages.manager_loaded);
      }}
      managerBootstrapOpen?.addEventListener("click", async () => {{
        const token = bootstrapTokenFromFragment();
        if (!token) {{ setManagerFeedback(managerMessages.manager_load_failed, "error"); return; }}
        managerBootstrapOpen.disabled = true;
        history.replaceState(null, "", window.location.pathname + window.location.search);
        try {{
          const login = await fetch("../admin/bootstrap", {{
            method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify({{ token }})
          }});
          if (!login.ok) throw new Error("bootstrap");
          await openManagerSession(login);
        }} catch {{
          setManagerFeedback(managerMessages.manager_load_failed, "error");
        }} finally {{
          managerBootstrapOpen.disabled = false;
        }}
      }});
      managerLoad?.addEventListener("click", async () => {{
        setManagerFeedback(managerMessages.manager_loading, "success", false);
        try {{
          const login = await fetch(
            `${{managerApiBase}}/${{ingressSso ? "ingress-session" : "session"}}`,
            ingressSso
              ? {{ method: "POST" }}
              : {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify({{ password: managerPassword.value }}) }}
          );
          if (!login.ok) throw new Error("login");
          await openManagerSession(login);
        }} catch {{
          setManagerFeedback(managerMessages.manager_load_failed, "error");
        }}
      }});
      managerRefresh.addEventListener("click", async () => {{
        managerRefresh.disabled = true;
        setManagerFeedback(managerMessages.manager_loading, "success", false);
        try {{ await loadManager(); setManagerFeedback(managerMessages.manager_loaded); }}
        catch {{ setManagerFeedback(managerMessages.manager_load_failed, "error"); }}
        finally {{ managerRefresh.disabled = false; }}
      }});
      managerDownloads.addEventListener("change", updateManagerControls);
      managerCancelOpen.addEventListener("click", () => {{
        if (!selectedDownloads().length) return;
        managerCancelPanel.hidden = false;
        managerCancelConfirm.textContent = managerMessages.manager_cancel_confirm;
        managerConfirmation.focus();
      }});
      managerConfirmation.addEventListener("input", () => {{
        managerCancelConfirm.disabled = managerConfirmation.value !== cancellationPhrase();
      }});
      document.querySelectorAll('[data-manager-action="pause"], [data-manager-action="resume"]').forEach((button) => button.addEventListener("click", async () => {{
        const hashes = selectedDownloads();
        const action = button.dataset.managerAction;
        if (!managerCsrf || !hashes.length) return;
        try {{
          const response = await fetch(`${{managerApiBase}}/downloads`, {{
            method: "PATCH", headers: {{ "Content-Type": "application/json", "X-CSRF-Token": managerCsrf }}, body: JSON.stringify({{ hashes, action }})
          }});
          if (!response.ok) throw new Error("mutation");
          await loadManager();
          setManagerFeedback(action === "pause" ? managerMessages.manager_pause_completed : managerMessages.manager_resume_completed);
        }} catch {{ setManagerFeedback(managerMessages.manager_update_failed, "error"); }}
      }}));
      managerCancelConfirm.addEventListener("click", async () => {{
        const hashes = selectedDownloads();
        if (!managerCsrf || !hashes.length || managerConfirmation.value !== cancellationPhrase()) return;
        try {{
          const response = await fetch(`${{managerApiBase}}/downloads`, {{
            method: "DELETE", headers: {{ "Content-Type": "application/json", "X-CSRF-Token": managerCsrf }}, body: JSON.stringify({{ hashes, confirmation: managerConfirmation.value }})
          }});
          if (!response.ok) throw new Error("mutation");
          await loadManager();
          setManagerFeedback(managerMessages.manager_cancel_completed);
        }} catch {{ setManagerFeedback(managerMessages.manager_cancel_failed, "error"); }}
      }});
    """
        if ingress_sso
        else ""
    )

    manager_styles = (
        """\
      .manager-settings { overflow: hidden; margin-top: 1.5rem; border: 1px solid rgba(124,227,160,.28); border-radius: 1rem; background: linear-gradient(135deg, rgba(26, 67, 51, .5), rgba(5, 12, 24, .5)); box-shadow: 0 .8rem 2rem rgba(0,0,0,.14); }
      .manager-settings summary { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1.15rem 1.2rem; color: #fff; background: rgba(124,227,160,.08); cursor: pointer; list-style: none; }
      .manager-settings summary::-webkit-details-marker { display: none; }
      .manager-title { font-size: 1.1rem; font-weight: 850; letter-spacing: -.015em; }
      .manager-subtitle { color: #9fdcb4; font-size: .76rem; font-weight: 750; letter-spacing: .04em; text-transform: uppercase; }
      .manager-settings > .profile-content { padding-top: 1.2rem; }
      .manager-settings .manager-intro { margin: 0; color: #c6d4c9; font-size: .9rem; line-height: 1.55; }
      .profile-content { display: grid; gap: 1rem; padding: 0 1.1rem 1.1rem; }
      .profile-content p { margin: 0; color: #9dacbd; font-size: .88rem; line-height: 1.5; }
      .profile-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .9rem; }
      .profile-group { display: grid; gap: .9rem; margin: 0; padding: 1rem; border: 1px solid rgba(255,255,255,.1); border-radius: .8rem; }
      .profile-group legend { padding: 0 .35rem; color: #dbe5f0; font-size: .8rem; font-weight: 800; }
      .profile-content input, .profile-content select { width: 100%; margin-top: .45rem; padding: .72rem; border: 1px solid rgba(255,255,255,.16); border-radius: .65rem; color: #edf2f7; background: #09111f; font: inherit; }
      .profile-content input[type="checkbox"] { width: auto; margin: 0 .45rem 0 0; accent-color: #7ce3a0; }
      .profile-content label { margin: 0; }
      .checkbox-label { display: flex; align-items: center; color: #dbe5f0; font-size: .9rem; font-weight: 700; }
      .field-hint { color: #8190a4; font-size: .75rem; font-weight: 400; }
      .profile-feedback, .action-feedback { min-height: 1.25rem; color: #9dacbd; font-size: .85rem; line-height: 1.45; }
      .profile-feedback[data-kind="success"], .action-feedback[data-kind="success"] { color: #8eeaac; }
      .profile-feedback[data-kind="error"], .action-feedback[data-kind="error"] { color: #f0a0a0; }
      #download-manager [hidden] { display: none !important; }
      #download-manager .manager-session { display: flex; align-items: center; justify-content: space-between; gap: .75rem; padding: .75rem 0; }
      #download-manager .manager-session strong { color: #8eeaac; font-size: .9rem; }
      #download-manager .manager-feedback { min-height: 1.25rem; }
      #download-manager .manager-empty, #download-manager .manager-library-empty { margin: 0; padding: 1rem; border-radius: .75rem; background: rgba(255,255,255,.055); color: #b9c5d4; }
      #download-manager .manager-download-list, #download-manager .manager-library-list { display: grid; gap: .6rem; margin: 0; padding: 0; list-style: none; }
      #download-manager .manager-download-row, #download-manager .manager-library-card { min-width: 0; padding: .8rem; border: 1px solid rgba(255,255,255,.1); border-radius: .75rem; background: rgba(5,12,24,.28); }
      #download-manager .manager-download-row label { display: flex; align-items: flex-start; gap: .65rem; margin: 0; }
      #download-manager .manager-download-name, #download-manager .manager-library-name { overflow-wrap: anywhere; color: #fff; font-weight: 750; }
      #download-manager .manager-meta { display: block; margin-top: .2rem; color: #9dacbd; font-size: .78rem; font-weight: 500; }
      #download-manager .manager-toolbar { display: grid; gap: .7rem; margin-top: 1rem; }
      #download-manager .manager-selection-count { color: #9dacbd; font-size: .82rem; }
      #download-manager .manager-toolbar .actions { margin: 0; }
      #download-manager .button.destructive { border-color: rgba(240,160,160,.5); color: #fff; background: #9e3740; }
      #download-manager .button.destructive:hover { background: #bd4852; }
      #download-manager .button:disabled { cursor: not-allowed; opacity: .52; }
      #download-manager .manager-cancel-panel { display: grid; gap: .7rem; padding: 1rem; border: 1px solid rgba(240,160,160,.45); border-radius: .8rem; background: rgba(104,24,35,.24); }
      #download-manager .manager-cancel-panel h4, #download-manager .manager-cancel-panel p { margin: 0; }
      #download-manager .manager-library-card details { margin-top: .55rem; color: #9dacbd; font-size: .78rem; }
      #download-manager .manager-library-card summary { cursor: pointer; }
      #download-manager .manager-library-card code { margin-top: .45rem; padding: .55rem; font-size: .74rem; }
      #download-manager .manager-network { margin-top: 1rem; border: 1px solid rgba(255,255,255,.1); border-radius: .8rem; }
      #download-manager .manager-network summary { padding: .85rem; color: #fff; font-weight: 750; cursor: pointer; }
      #download-manager .manager-network-body { display: grid; gap: .7rem; padding: 0 .85rem .85rem; }
      #download-manager .manager-network-states { display: grid; grid-template-columns: repeat(3, 1fr); gap: .5rem; }
      #download-manager .manager-network-state { padding: .55rem; border-radius: .55rem; background: rgba(255,255,255,.055); color: #9dacbd; font-size: .72rem; }
      #download-manager .manager-network-state strong { display: block; margin-top: .15rem; color: #edf2f7; font-size: .8rem; }
    """
        if ingress_sso
        else ""
    )

    return f"""<!doctype html>
<html lang="{locale}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#101827">
    <title>{t("page_title")}</title>
    <style>
      :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; min-height: 100vh; color: #edf2f7; background: radial-gradient(circle at 20% 0%, #273f67 0, transparent 38rem), radial-gradient(circle at 100% 100%, #243b31 0, transparent 32rem), #101827; }}
      main {{ width: min(100% - 2rem, 46rem); margin: 0 auto; padding: 4.5rem 0 3rem; }}
      .brand {{ display: inline-flex; align-items: center; gap: .7rem; color: #fff; font-size: 1.35rem; font-weight: 700; text-decoration: none; }}
      .brand img {{ width: 2.25rem; height: auto; image-rendering: auto; }}
      .language {{ float: right; display: flex; align-items: center; gap: .55rem; color: #9dacbd; font-size: .82rem; }}
      .language a {{ color: #dbe5f0; text-decoration: none; }}
      .language a[aria-current="page"] {{ color: #8eeaac; font-weight: 800; }}
      .card {{ margin-top: 2.5rem; padding: clamp(1.5rem, 5vw, 3rem); border: 1px solid rgba(255,255,255,.12); border-radius: 1.5rem; background: rgba(18, 29, 47, .78); box-shadow: 0 2rem 5rem rgba(0,0,0,.28); backdrop-filter: blur(18px); }}
      .eyebrow {{ margin: 0 0 .8rem; color: #78d39a; font-size: .75rem; font-weight: 800; letter-spacing: .12em; }}
      h1 {{ max-width: 38rem; margin: 0; color: #fff; font-size: clamp(2rem, 6vw, 3.5rem); line-height: 1.08; letter-spacing: -.045em; }}
      .intro {{ max-width: 40rem; margin: 1.25rem 0 2rem; color: #b9c5d4; font-size: 1.08rem; line-height: 1.65; }}
      .readiness {{ margin: 0 0 2rem; padding: 1rem; border: 1px solid rgba(255,255,255,.1); border-radius: 1rem; background: rgba(5, 12, 24, .38); }}
      .readiness h2 {{ margin: 0 0 .8rem; color: #fff; font-size: .9rem; }}
      .status-grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: .55rem; }}
      .status {{ min-width: 0; padding: .65rem; border-radius: .65rem; background: rgba(255,255,255,.055); }}
      .status-label {{ display: block; overflow: hidden; color: #9dacbd; font-size: .7rem; text-overflow: ellipsis; white-space: nowrap; }}
      .status-value {{ display: block; overflow: hidden; margin-top: .25rem; color: #e3ebf4; font-size: .78rem; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }}
      .status[data-state="connected"] .status-value, .status[data-state="ready"] .status-value, .status[data-state="configured"] .status-value {{ color: #8eeaac; }}
      .status[data-state="connecting"] .status-value {{ color: #f7d978; }}
      .status[data-state="limited"] .status-value {{ color: #f7d978; }}
      .status[data-state="unavailable"] .status-value, .status[data-state="disconnected"] .status-value {{ color: #f0a0a0; }}
      .readiness-hint {{ margin: .8rem 0 0; color: #9dacbd; font-size: .82rem; line-height: 1.5; }}
      .features {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem; margin: 0 0 2rem; }}
      .feature {{ min-height: 7.5rem; padding: 1rem; border-radius: 1rem; background: rgba(255,255,255,.055); color: #cbd5e1; font-size: .88rem; line-height: 1.45; }}
      .feature strong {{ display: block; margin-bottom: .3rem; color: #fff; font-size: .92rem; }}
      label {{ display: block; margin-bottom: .7rem; color: #dbe5f0; font-size: .9rem; font-weight: 700; }}
      code {{ display: block; overflow-wrap: anywhere; padding: 1rem 1.1rem; border: 1px solid rgba(255,255,255,.12); border-radius: .8rem; background: #09111f; color: #a7f3c3; font: .84rem/1.55 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
      .actions {{ display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1rem; }}
      .button {{ display: inline-flex; align-items: center; justify-content: center; min-height: 3rem; padding: .75rem 1.1rem; border: 1px solid transparent; border-radius: .75rem; color: #07110c; background: #7ce3a0; font: inherit; font-weight: 800; text-decoration: none; cursor: pointer; }}
      .button:hover {{ background: #9bf0b8; }}
      .button.secondary {{ border-color: rgba(255,255,255,.18); color: #edf2f7; background: transparent; }}
      .button.secondary:hover {{ background: rgba(255,255,255,.08); }}
      .hint {{ margin: 1.1rem 0 0; color: #9dacbd; font-size: .86rem; line-height: 1.55; }}
      .hint strong {{ color: #dbe5f0; }}
      .profile-settings {{ margin-top: 1.5rem; border: 1px solid rgba(255,255,255,.1); border-radius: 1rem; background: rgba(5, 12, 24, .32); }}
      .profile-settings summary {{ padding: 1rem 1.1rem; color: #fff; font-weight: 800; cursor: pointer; }}
      {manager_styles}
      footer {{ margin-top: 1.5rem; color: #8190a4; font-size: .78rem; text-align: center; }}
      @media (max-width: 36rem) {{ main {{ padding-top: 2rem; }} .language {{ margin-top: .5rem; }} .features, .profile-grid {{ grid-template-columns: 1fr; }} .feature {{ min-height: auto; }} .status-grid {{ grid-template-columns: repeat(2, 1fr); }} .button {{ width: 100%; }} }}
    </style>
  </head>
  <body>
    <main>
      <a class="brand" href="configure" aria-label="{t("brand_configuration")}">
        <img src="{logo_url}" alt="{t("amule_logo")}">
        <span>aMulio</span>
      </a>
      <nav class="language" aria-label="{t("language")}"><span>{t("language")}:</span>{language_links}</nav>
      <section class="card" aria-labelledby="install-title">
        <p class="eyebrow">{t("eyebrow")}</p>
        <h1 id="install-title">{t("heading")}</h1>
        <p class="intro">{t("intro")}</p>
        <section class="readiness" id="readiness" data-status-url="{status_url}" aria-live="polite" aria-label="{t("readiness")}">
          <h2>{t("readiness")}</h2>
          <div class="status-grid">
            <div class="status" data-key="amuleapi"><span class="status-label">{t("amuleapi")}</span><span class="status-value">{t("checking")}</span></div>
            <div class="status" data-key="ed2k"><span class="status-label">{t("ed2k")}</span><span class="status-value">{t("checking")}</span></div>
            <div class="status" data-key="kad"><span class="status-label">{t("kad")}</span><span class="status-value">{t("checking")}</span></div>
            <div class="status" data-key="peer_access"><span class="status-label">{t("peer_access")}</span><span class="status-value">{t("checking")}</span></div>
            <div class="status" data-key="incoming_storage"><span class="status-label">{t("incoming_storage")}</span><span class="status-value">{t("checking")}</span></div>
            <div class="status" data-key="public_url"><span class="status-label">{t("public_url")}</span><span class="status-value">{t("checking")}</span></div>
          </div>
          <p class="readiness-hint" id="readiness-hint">{t("checking")}</p>
        </section>
        <div class="features">
          <div class="feature"><strong>{t("private_title")}</strong>{t("private_body")}</div>
          <div class="feature"><strong>{t("self_hosted_title")}</strong>{t("self_hosted_body")}</div>
          <div class="feature"><strong>{t("ready_title")}</strong>{t("ready_body")}</div>
        </div>
        <label for="manifest-url">{t("manifest_label")}</label>
        <code id="manifest-url">{safe_manifest_url}</code>
        <div class="actions">
          <a class="button" href="{stremio_url}">{t("install")}</a>
          <button class="button secondary" type="button" id="copy-button">{t("copy")}</button>
        </div>
        <p class="action-feedback" id="action-feedback" role="status" aria-live="polite"></p>
        <p class="hint"><strong>{t("tip_label")}</strong> {t("tip")}</p>
        <details class="profile-settings"{profile_hidden}>
          <summary>{t("profile_settings")}</summary>
          <form class="profile-content" id="profile-form">
            <p>{t("profile_intro")}</p>

            <label for="admin-password">{t("admin_password")}
              <input id="admin-password" name="password" type="password" autocomplete="current-password" required{profile_disabled}>
            </label>
            <fieldset class="profile-group"{profile_disabled}>
              <legend>{t("profile_basic")}</legend>
              <label for="profile-language">{t("profile_language")}
                <select id="profile-language" name="ui_language">
                  <option value="en"{" selected" if locale == "en" else ""}>{t("english")}</option>
                  <option value="es"{" selected" if locale == "es" else ""}>{t("spanish")}</option>
                </select>
              </label>
              <p class="field-hint">{t("storage_note")}</p>
            </fieldset>
            <fieldset class="profile-group"{profile_disabled}>
              <legend>{t("profile_search")}</legend>
              <label for="search-languages">{t("search_languages")}
                <input id="search-languages" name="search_languages" value="en,es" pattern="[A-Za-z0-9,-\\s]+" required>
                <span class="field-hint">{t("search_languages_hint")}</span>
              </label>
              <label class="checkbox-label"><input name="allow_season_packs" type="checkbox">{t("season_packs")}</label>
            </fieldset>
            <fieldset class="profile-group"{profile_disabled}>
              <legend>{t("profile_advanced")}</legend>
              <div class="profile-grid">
              <label for="result-limit">{t("result_limit")}
                <input id="result-limit" name="result_limit" type="number" min="1" max="50" value="10" required>
              </label>
              <label for="maximum-size">{t("maximum_size")}
                <input id="maximum-size" name="maximum_size" type="number" min="0.1" max="100" step="0.1">
              </label>
              </div>
            </fieldset>
            <fieldset class="profile-group"{profile_disabled}>
              <legend>{t("profile_stream_display")}</legend>
              <label class="checkbox-label"><input name="show_stream_size" type="checkbox" checked>{t("stream_show_size")}</label>
              <label class="checkbox-label"><input name="show_stream_sources" type="checkbox" checked>{t("stream_show_sources")}</label>
              <label class="checkbox-label"><input name="show_stream_language" type="checkbox" checked>{t("stream_show_language")}</label>
              <label class="checkbox-label"><input name="show_stream_technical_details" type="checkbox" checked>{t("stream_show_technical")}</label>
            </fieldset>
            <button class="button" type="submit" id="profile-submit"{profile_disabled}>{t("create_profile")}</button>
            <div class="profile-feedback" id="profile-feedback" role="status"></div>
          </form>
        </details>
        {manager_section}
      </section>
      <footer>{t("footer")}</footer>
    </main>
    <script>
      const copyButton = document.getElementById("copy-button");
      let manifestUrl = document.getElementById("manifest-url").textContent;
      const manifestElement = document.getElementById("manifest-url");
      const installButton = document.querySelector(".actions .button");
      const actionFeedback = document.getElementById("action-feedback");
      const profileForm = document.getElementById("profile-form");
      const profileFeedback = document.getElementById("profile-feedback");
      const profileSubmit = document.getElementById("profile-submit");
      const readiness = document.getElementById("readiness");
      const readinessHint = document.getElementById("readiness-hint");
      const statusLabels = {status_labels};
      const readinessMessages = {json.dumps({key: translate(locale, key) for key in ("readiness_hint_disconnected", "readiness_hint_connecting", "readiness_hint_limited", "readiness_hint_peer_unknown", "readiness_hint_unavailable", "readiness_hint_ready")}, ensure_ascii=False).replace("</", "<\\/")};
      function setActionFeedback(message, kind) {{
        actionFeedback.textContent = message;
        actionFeedback.dataset.kind = kind;
      }}
      copyButton.addEventListener("click", async () => {{
        try {{
          await navigator.clipboard.writeText(manifestUrl);
          copyButton.textContent = "{t("copied")}";
          setActionFeedback("{t("copied")}", "success");
        }} catch {{
          copyButton.textContent = "{t("copy_failed")}";
          setActionFeedback("{t("copy_failed")}", "error");
        }}
        window.setTimeout(() => {{
          copyButton.textContent = "{t("copy")}";
          actionFeedback.textContent = "";
        }}, 2400);
      }});
      installButton.addEventListener("click", () => {{
        setActionFeedback("{t("install_feedback")}", "success");
      }});
      fetch(readiness.dataset.statusUrl, {{ cache: "no-store" }})
        .then((response) => {{ if (!response.ok) throw new Error("readiness unavailable"); return response.json(); }})
        .then((states) => {{
          Object.entries(states).forEach(([key, state]) => {{
            const item = readiness.querySelector(`[data-key="${{key}}"]`);
            if (!item) return;
            item.dataset.state = state;
            item.querySelector(".status-value").textContent = statusLabels[state] || statusLabels.unknown;
          }});
          const hints = [];
          if (states.amuleapi !== "connected") hints.push(readinessMessages.readiness_hint_unavailable);
          if (states.ed2k === "disconnected") hints.push(readinessMessages.readiness_hint_disconnected);
          if (states.kad === "connecting") hints.push(readinessMessages.readiness_hint_connecting);
          if (states.peer_access === "unknown") hints.push(readinessMessages.readiness_hint_peer_unknown);
          readinessHint.textContent = hints.length ? hints.join(" ") : readinessMessages.readiness_hint_ready;
        }})
        .catch(() => {{
          readiness.querySelectorAll(".status").forEach((item) => {{
            item.dataset.state = "unavailable";
            item.querySelector(".status-value").textContent = statusLabels.unavailable;
          }});
          readinessHint.textContent = readinessMessages.readiness_hint_unavailable;
        }});
      profileForm.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const form = new FormData(profileForm);
        const password = form.get("password");
        const searchLanguages = String(form.get("search_languages"))
          .split(",").map((value) => value.trim().toLowerCase()).filter(Boolean);
        const maximumSize = String(form.get("maximum_size")).trim();
        profileSubmit.disabled = true;
        profileSubmit.textContent = "{t("creating_profile")}";
        profileFeedback.textContent = "";
        try {{
          const login = await fetch("../admin/session", {{
            method: "POST", headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ password }})
          }});
          if (login.status === 404) throw new Error("disabled");
          if (!login.ok) throw new Error("login");
          const session = await login.json();
          const profile = await fetch("../admin/profiles", {{
            method: "POST", headers: {{ "Content-Type": "application/json", "X-CSRF-Token": session.csrf_token }},
            body: JSON.stringify({{
              ui_language: form.get("ui_language"), search_languages: searchLanguages,
              allow_season_packs: form.get("allow_season_packs") === "on",
              result_limit: Number(form.get("result_limit")),
              max_size_gb: maximumSize ? Number(maximumSize) : null,
              show_stream_size: form.get("show_stream_size") === "on",
              show_stream_sources: form.get("show_stream_sources") === "on",
              show_stream_language: form.get("show_stream_language") === "on",
              show_stream_technical_details: form.get("show_stream_technical_details") === "on"
            }})
          }});
          if (!profile.ok) throw new Error("profile");
          const created = await profile.json();
          const installation = await fetch(`../admin/profiles/${{created.id}}/installation`);
          if (!installation.ok) throw new Error("installation");
          manifestUrl = (await installation.json()).manifest_url;
          manifestElement.textContent = manifestUrl;
          installButton.href = "stremio://" + manifestUrl.replace(/^https?:\\/\\//, "");
          form.set("password", "");
          document.getElementById("admin-password").value = "";
          profileFeedback.dataset.kind = "success";
          profileFeedback.textContent = "{t("profile_created")}";
        }} catch (error) {{
          profileFeedback.dataset.kind = "error";
          profileFeedback.textContent = error.message === "disabled" ? "{t("admin_disabled")}" : "{t("admin_failed")}";
        }} finally {{
          profileSubmit.disabled = false;
          profileSubmit.textContent = "{t("create_profile")}";
        }}
      }});
      {manager_script}
    </script>
  </body>
</html>"""


def _profile_manifest_url(settings: Settings, profile: AddonProfile) -> str:
    return (
        f"{str(settings.public_url).rstrip('/')}/{settings.install_token.get_secret_value()}"
        f"/profile/{profile.id}/manifest.json"
    )


def _manifest(settings: Settings, profile: AddonProfile | None = None) -> dict:
    suffix = f".profile.{profile.id}" if profile is not None else ""
    language = profile.preferences.ui_language if profile is not None else "en"
    return {
        "id": f"com.alexruperez.amulio{suffix}",
        "version": "0.1.0",
        "name": "aMulio",
        "description": translate(language, "manifest_description"),
        "logo": (
            f"{str(settings.public_url).rstrip('/')}/assets/amule-logo.png?v={AMULE_LOGO_VERSION}"
        ),
        "catalogs": [],
        "resources": [{"name": "stream", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
        "types": ["movie", "series"],
        # Profiles are server-side and this manifest has no browser-side options.
        "behaviorHints": {"p2p": True},
    }


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
    return _manifest(settings)


@app.get("/{installation_token}/profile/{profile_id}/manifest.json")
async def profile_manifest(
    installation_token: str, profile_id: str, request: Request, profiles: Profiles
):
    settings = _settings(request)
    _require_install_token(installation_token, settings)
    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await _enforce_rate_limit(
        request,
        route="manifest",
        subject=f"{installation_token}:{profile.id}",
        limit=settings.manifest_rate_limit,
        settings=settings,
    )
    return _manifest(settings, profile)


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
    return await _stream_listing(
        media_type=media_type,
        media_id=media_id,
        request=request,
        api=api,
        metadata=metadata,
        cache=cache,
        search_locks=search_locks,
    )


@app.get("/{installation_token}/profile/{profile_id}/stream/{media_type}/{media_id}.json")
async def profile_streams(
    installation_token: str,
    profile_id: str,
    media_type: str,
    media_id: str,
    request: Request,
    response: Response,
    api: ApiClient,
    metadata: MetadataClient,
    cache: Cache,
    search_locks: SearchLocks,
    profiles: Profiles,
):
    settings = _settings(request)
    _require_install_token(installation_token, settings)
    profile = profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await _enforce_rate_limit(
        request,
        route="stream",
        subject=f"{installation_token}:{profile.id}",
        limit=settings.stream_rate_limit,
        settings=settings,
    )
    response.headers["Cache-Control"] = "no-store"
    if media_type not in {"movie", "series"} or not media_id.startswith("tt"):
        return {"streams": []}
    return await _stream_listing(
        media_type=media_type,
        media_id=media_id,
        request=request,
        api=api,
        metadata=metadata,
        cache=cache,
        search_locks=search_locks,
        preferences=profile.preferences,
        cache_scope=f"profile:{profile.id}",
    )


async def _stream_listing(
    *,
    media_type: str,
    media_id: str,
    request: Request,
    api: ApiClient,
    metadata: MetadataClient,
    cache: Cache,
    search_locks: SearchLocks,
    preferences: ProfilePreferences | None = None,
    cache_scope: str = "default",
) -> dict:
    settings = _settings(request)
    locale = preferences.ui_language if preferences is not None else "en"

    try:
        candidates = await _discover_candidates(
            media_type=media_type,
            media_id=media_id,
            api=api,
            metadata=metadata,
            cache=cache,
            settings=settings,
            search_locks=search_locks,
            preferences=preferences,
            cache_scope=cache_scope,
        )
    except (AmuleApiError, MetadataError):
        return {
            "streams": [
                _status_stream(
                    settings,
                    kind="unavailable",
                    label=translate(locale, "stream_unavailable"),
                    detail=translate(locale, "stream_unavailable_detail"),
                    locale=locale,
                )
            ]
        }

    if not candidates:
        return {
            "streams": [
                _status_stream(
                    settings,
                    kind="no_results",
                    label=translate(locale, "stream_no_results"),
                    detail=translate(locale, "stream_no_results_detail"),
                    locale=locale,
                )
            ]
        }
    states = cache.file_state_details([candidate.hash for candidate in candidates])
    return {
        "streams": [
            _stream_object(
                candidate,
                request,
                file_state=states.get(candidate.hash),
                locale=locale,
                preferences=preferences,
            )
            for candidate in candidates
        ]
    }


@app.api_route("/play/{token}", methods=["GET", "HEAD"])
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
        payload = verify(token, secret=settings.token_secret.get_secret_value())
        candidate = Candidate.model_validate(payload["candidate"])
    except (InvalidToken, KeyError):
        raise HTTPException(status_code=404) from None
    locale = resolve_locale(
        payload.get("locale") if isinstance(payload.get("locale"), str) else None
    )

    if candidate.local_path is not None:
        _safe_media_path(candidate.local_path, settings=settings)
        return RedirectResponse(f"/file/{token}", status_code=307)

    # Stremio probes stream URLs with HEAD before issuing GET. HEAD must not
    # enqueue a P2P download; direct it to /file, which reports completion
    # status without changing aMule state.
    if request.method == "HEAD":
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
        return status_video("unavailable", locale=locale)

    if queued:
        return status_video("started", locale=locale)
    file_state = cache.file_state(candidate.hash)
    return status_video(
        "downloading" if file_state and file_state.state == "downloading" else "started",
        locale=locale,
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
