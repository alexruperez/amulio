from amulio.metadata import MediaMetadata


def test_episode_search_query_uses_stremio_episode_scope():
    metadata = MediaMetadata(title="The Example Show", year=2026, season=2, episode=4)

    assert metadata.search_query == "The Example Show S02E04"


def test_movie_search_query_prefers_title_and_year():
    metadata = MediaMetadata(title="An Example Film", year=2026)

    assert metadata.search_query == "An Example Film 2026"
