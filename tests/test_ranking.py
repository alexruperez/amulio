from amulio.metadata import MediaMetadata
from amulio.models import AmuleSearchResult
from amulio.ranking import rank_results


def _result(name: str, file_hash: str = "a" * 32) -> AmuleSearchResult:
    return AmuleSearchResult(
        hash=file_hash,
        name=name,
        size=2_000_000_000,
        sources={"total": 20, "complete": 10},
    )


def test_rank_results_keeps_matching_episode_and_rejects_other_episode():
    metadata = MediaMetadata(title="Example Show", season=2, episode=4)
    results = [
        _result("Example.Show.S02E04.1080p.WEB.mkv"),
        _result("Example.Show.S02E05.1080p.WEB.mkv", "b" * 32),
    ]

    candidates = rank_results(results, metadata)

    assert [candidate.hash for candidate in candidates] == ["a" * 32]
    assert candidates[0].quality == "1080p"


def test_rank_results_rejects_archives_and_samples():
    metadata = MediaMetadata(title="Example Film", year=2026)
    results = [
        _result("Example.Film.2026.1080p.sample.mkv"),
        _result("Example.Film.2026.1080p.rar", "b" * 32),
    ]

    assert rank_results(results, metadata) == []
