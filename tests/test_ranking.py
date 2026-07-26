import json
from pathlib import Path

from amulio.metadata import MediaMetadata, TitleVariant
from amulio.models import AmuleSearchResult
from amulio.ranking import rank_results


def _result(name: str, file_hash: str = "a" * 32, size: int = 2_000_000_000) -> AmuleSearchResult:
    return AmuleSearchResult(
        hash=file_hash,
        name=name,
        size=size,
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


def test_rank_results_accepts_a_configured_title_alias():
    metadata = MediaMetadata(
        title="La Película de Ejemplo",
        year=2026,
        aliases=(TitleVariant(title="The Example Film", language="en"),),
    )

    candidates = rank_results([_result("The.Example.Film.2026.1080p.mkv")], metadata)

    assert [candidate.hash for candidate in candidates] == ["a" * 32]


def test_rank_results_rejects_implausibly_small_and_large_video_files():
    metadata = MediaMetadata(title="Example Film", year=2026)
    results = [
        _result("Example.Film.2026.1080p.mkv", size=600_000_000),
        _result("Example.Film.2026.1080p.mkv", "b" * 32, size=90_000_000_000),
    ]

    assert rank_results(results, metadata) == []


def test_rank_results_rejects_episode_season_packs_unless_enabled():
    metadata = MediaMetadata(title="Example Show", season=2, episode=4)
    season_pack = _result("Example.Show.S02E04-E10.1080p.mkv")

    assert rank_results([season_pack], metadata) == []
    assert [
        candidate.hash
        for candidate in rank_results([season_pack], metadata, allow_season_packs=True)
    ] == ["a" * 32]


def test_rank_results_respects_configured_extension_lists():
    metadata = MediaMetadata(title="Example Film", year=2026)
    result = _result("Example.Film.2026.1080p.mp4")

    assert rank_results([result], metadata, allowed_extensions=(".mkv",)) == []
    assert (
        rank_results([result], metadata, allowed_extensions=(".mp4",), denied_extensions=(".mp4",))
        == []
    )


def test_ranking_fixture_prefers_language_codec_hdr_and_release_group_signals():
    fixture_path = Path(__file__).parent / "fixtures" / "ranking_cases.json"
    fixture = json.loads(fixture_path.read_text())["localized_movie"]
    metadata = MediaMetadata.model_validate(fixture["metadata"])
    results = [AmuleSearchResult.model_validate(result) for result in fixture["results"]]

    candidates = rank_results(results, metadata, preferred_languages=("es", "en"))

    assert [candidate.hash for candidate in candidates] == ["b" * 32, "a" * 32]
    assert candidates[0].language == "es"
    assert candidates[0].codec == "hevc"
    assert candidates[0].hdr is True
    assert candidates[0].release_group == "QUALITY"
