import re
import unicodedata
from pathlib import Path

from amulio.ed2k import build_file_link
from amulio.metadata import MediaMetadata
from amulio.models import AmuleSearchResult, Candidate

DEFAULT_VIDEO_EXTENSIONS = (".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm")
DEFAULT_DENIED_EXTENSIONS = (".exe", ".iso", ".rar", ".zip")
REJECTED_TERMS = {"sample", "trailer", "repack"}
QUALITY_PATTERNS = ("2160p", "1080p", "720p", "576p", "480p")
QUALITY_MINIMUM_SIZES = {
    "480p": 200_000_000,
    "576p": 300_000_000,
    "720p": 400_000_000,
    "1080p": 700_000_000,
    "2160p": 2_000_000_000,
}
MINIMUM_SHORT_FILM_SIZE = 15_000_000
LANGUAGE_TOKENS = {
    "en": {"en", "eng", "english"},
    "es": {"es", "esp", "spanish", "castellano"},
    "fr": {"fr", "fra", "fre", "french"},
    "de": {"de", "ger", "deu", "german"},
    "it": {"it", "ita", "italian"},
    "pt": {"pt", "por", "portuguese"},
}
CODEC_PATTERNS = {
    "hevc": ("hevc", "x265", "h265"),
    "avc": ("avc", "x264", "h264"),
    "av1": ("av1",),
}
HDR_PATTERNS = ("hdr", "hdr10", "hdr10plus", "dolby vision", "dovi", "dv")


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _extension(name: str) -> str:
    return Path(name).suffix.lower()


def _has_allowed_extension(
    name: str, *, allowed_extensions: tuple[str, ...], denied_extensions: tuple[str, ...]
) -> bool:
    extension = _extension(name)
    return extension in allowed_extensions and extension not in denied_extensions


def _episode_matches(name: str, season: int, episode: int) -> bool:
    patterns = (
        rf"\bs{season:02}e{episode:02}\b",
        rf"\b{season}x{episode:02}\b",
        rf"\bseason[ ._-]?{season}[ ._-]?episode[ ._-]?{episode}\b",
    )
    return any(re.search(pattern, name, flags=re.IGNORECASE) for pattern in patterns)


def _is_season_pack(name: str) -> bool:
    normalized = _normalize(name)
    return bool(
        re.search(r"\b(?:complete|full)[ ._-]?season\b", name, flags=re.IGNORECASE)
        or re.search(
            r"\bs\d{1,2}e\d{1,2}(?:[ ._-]?e\d{1,2}|-\d{1,2})\b",
            name,
            flags=re.IGNORECASE,
        )
        or "season pack" in normalized
    )


def _quality(name: str) -> str | None:
    lowered = name.lower()
    return next((quality for quality in QUALITY_PATTERNS if quality in lowered), None)


def _plausible_size(
    result: AmuleSearchResult, metadata: MediaMetadata, quality: str | None
) -> bool:
    is_episode = metadata.season is not None and metadata.episode is not None
    # A short film can be both legitimate and substantially smaller than a
    # feature film. Explicit quality labels still use their stricter minimums.
    minimum = 100_000_000 if is_episode else MINIMUM_SHORT_FILM_SIZE
    maximum = 25_000_000_000 if is_episode else 80_000_000_000
    if quality is not None:
        minimum = max(minimum, QUALITY_MINIMUM_SIZES[quality])
    return minimum <= result.size <= maximum


def _language(name_tokens: set[str]) -> str | None:
    return next(
        (language for language, tokens in LANGUAGE_TOKENS.items() if name_tokens & tokens), None
    )


def _codec(normalized_name: str) -> str | None:
    return next(
        (
            codec
            for codec, patterns in CODEC_PATTERNS.items()
            if any(pattern in normalized_name for pattern in patterns)
        ),
        None,
    )


def _release_group(name: str) -> str | None:
    stem = Path(name).stem
    match = re.search(r"-(?P<group>[A-Za-z0-9]{2,16})$", stem)
    return match.group("group") if match else None


def _ranking_signals(
    name: str, name_tokens: set[str]
) -> tuple[str | None, str | None, bool, str | None]:
    normalized_name = _normalize(name)
    return (
        _language(name_tokens),
        _codec(normalized_name),
        any(pattern in normalized_name for pattern in HDR_PATTERNS),
        _release_group(name),
    )


def rank_result(
    result: AmuleSearchResult,
    metadata: MediaMetadata,
    *,
    allowed_extensions: tuple[str, ...] = DEFAULT_VIDEO_EXTENSIONS,
    denied_extensions: tuple[str, ...] = DEFAULT_DENIED_EXTENSIONS,
    allow_season_packs: bool = False,
    preferred_languages: tuple[str, ...] = (),
) -> Candidate | None:
    if not _has_allowed_extension(
        result.name, allowed_extensions=allowed_extensions, denied_extensions=denied_extensions
    ):
        return None
    normalized_name = _normalize(result.name)
    if any(term in normalized_name.split() for term in REJECTED_TERMS):
        return None

    name_tokens = set(normalized_name.split())
    title_tokens, matching_title_tokens = max(
        (
            (title_tokens, title_tokens & name_tokens)
            for title in metadata.titles
            if (title_tokens := set(_normalize(title).split()))
        ),
        key=lambda match: len(match[1]),
        default=(set(), set()),
    )
    if not title_tokens or len(matching_title_tokens) / len(title_tokens) < 0.8:
        return None

    quality = _quality(result.name)
    if not _plausible_size(result, metadata, quality):
        return None

    score = len(matching_title_tokens) * 20
    if metadata.season is not None and metadata.episode is not None:
        if not _episode_matches(result.name, metadata.season, metadata.episode):
            return None
        if not allow_season_packs and _is_season_pack(result.name):
            return None
        score += 80
    elif metadata.year is not None:
        if str(metadata.year) in normalized_name:
            score += 30
        elif re.search(r"\b(19|20)\d{2}\b", normalized_name):
            score -= 25

    complete_sources = result.sources.get("complete", 0)
    total_sources = result.sources.get("total", 0)
    score += min(complete_sources, 50) * 2 + min(total_sources, 100) // 5
    if quality:
        score += 10
    language, codec, hdr, release_group = _ranking_signals(result.name, name_tokens)
    if language in preferred_languages:
        score += (len(preferred_languages) - preferred_languages.index(language)) * 10
    if codec:
        score += 4
    if hdr:
        score += 4
    if release_group:
        score += 3

    try:
        link = build_file_link(name=result.name, size=result.size, file_hash=result.hash)
    except ValueError:
        return None
    return Candidate(
        hash=result.hash.lower(),
        name=result.name,
        size=result.size,
        sources_total=total_sources,
        sources_complete=complete_sources,
        ed2k_link=link,
        quality=quality,
        language=language,
        codec=codec,
        hdr=hdr,
        release_group=release_group,
        score=score,
    )


def rank_results(
    results: list[AmuleSearchResult],
    metadata: MediaMetadata,
    *,
    allowed_extensions: tuple[str, ...] = DEFAULT_VIDEO_EXTENSIONS,
    denied_extensions: tuple[str, ...] = DEFAULT_DENIED_EXTENSIONS,
    allow_season_packs: bool = False,
    preferred_languages: tuple[str, ...] = (),
) -> list[Candidate]:
    unique: dict[str, Candidate] = {}
    for result in results:
        candidate = rank_result(
            result,
            metadata,
            allowed_extensions=allowed_extensions,
            denied_extensions=denied_extensions,
            allow_season_packs=allow_season_packs,
            preferred_languages=preferred_languages,
        )
        if candidate is None:
            continue
        existing = unique.get(candidate.hash)
        if existing is None or candidate.score > existing.score:
            unique[candidate.hash] = candidate
    return sorted(unique.values(), key=lambda candidate: candidate.score, reverse=True)
