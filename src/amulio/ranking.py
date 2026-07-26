import re
import unicodedata

from amulio.ed2k import build_file_link
from amulio.metadata import MediaMetadata
from amulio.models import AmuleSearchResult, Candidate

VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm"}
REJECTED_TERMS = {"sample", "trailer", "rar", "repack", "zip"}
QUALITY_PATTERNS = ("2160p", "1080p", "720p", "576p", "480p")


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _has_supported_extension(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.endswith(extension) for extension in VIDEO_EXTENSIONS)


def _episode_matches(name: str, season: int, episode: int) -> bool:
    patterns = (
        rf"\bs{season:02}e{episode:02}\b",
        rf"\b{season}x{episode:02}\b",
        rf"\bseason[ ._-]?{season}[ ._-]?episode[ ._-]?{episode}\b",
    )
    return any(re.search(pattern, name, flags=re.IGNORECASE) for pattern in patterns)


def _quality(name: str) -> str | None:
    lowered = name.lower()
    return next((quality for quality in QUALITY_PATTERNS if quality in lowered), None)


def rank_result(result: AmuleSearchResult, metadata: MediaMetadata) -> Candidate | None:
    if not _has_supported_extension(result.name):
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

    score = len(matching_title_tokens) * 20
    if metadata.season is not None and metadata.episode is not None:
        if not _episode_matches(result.name, metadata.season, metadata.episode):
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
    quality = _quality(result.name)
    if quality:
        score += 10

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
        score=score,
    )


def rank_results(results: list[AmuleSearchResult], metadata: MediaMetadata) -> list[Candidate]:
    unique: dict[str, Candidate] = {}
    for result in results:
        candidate = rank_result(result, metadata)
        if candidate is None:
            continue
        existing = unique.get(candidate.hash)
        if existing is None or candidate.score > existing.score:
            unique[candidate.hash] = candidate
    return sorted(unique.values(), key=lambda candidate: candidate.score, reverse=True)
