import hashlib
from pathlib import Path

from amulio.config import Settings
from amulio.metadata import MediaMetadata
from amulio.models import AmuleSearchResult, Candidate
from amulio.ranking import rank_result


def discover_local_media(
    metadata: MediaMetadata,
    settings: Settings,
    *,
    allow_season_packs: bool | None = None,
    preferred_languages: tuple[str, ...] | None = None,
) -> list[Candidate]:
    """Return completed video files in aMule's allowed incoming directories.

    Local files are ranked with the same title and episode rules as eD2K search
    results, but retain their real size and can be played without re-queuing.
    """
    candidates: list[Candidate] = []
    if allow_season_packs is None:
        allow_season_packs = settings.allow_season_packs
    if preferred_languages is None:
        preferred_languages = settings.search_languages
    for root_name in settings.media_roots:
        root = Path(root_name)
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in settings.allowed_extensions:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            fingerprint = hashlib.blake2s(
                f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode(), digest_size=16
            ).hexdigest()
            # P2P results have plausibility thresholds. A local completed file is
            # already trusted by the operator, so only its name must match.
            ranked = rank_result(
                AmuleSearchResult(
                    hash=fingerprint,
                    name=path.name,
                    size=max(stat.st_size, 2_000_000_000),
                    sources={"complete": 1, "total": 1},
                ),
                metadata,
                allowed_extensions=settings.allowed_extensions,
                denied_extensions=settings.denied_extensions,
                allow_season_packs=allow_season_packs,
                preferred_languages=preferred_languages,
            )
            if ranked is not None:
                candidates.append(
                    ranked.model_copy(
                        update={"size": stat.st_size, "local_path": str(path.resolve())}
                    )
                )
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
