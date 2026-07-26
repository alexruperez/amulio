import httpx

from amulio.metadata import CinemetaClient, MediaMetadata, TitleVariant


def test_episode_search_query_uses_stremio_episode_scope():
    metadata = MediaMetadata(title="The Example Show", year=2026, season=2, episode=4)

    assert metadata.search_query == "The Example Show S02E04"


def test_movie_search_query_prefers_title_and_year():
    metadata = MediaMetadata(title="An Example Film", year=2026)

    assert metadata.search_query == "An Example Film 2026"


def test_search_queries_include_language_ordered_aliases_and_episode_scope():
    metadata = MediaMetadata(
        title="La Serie de Ejemplo",
        aliases=(
            TitleVariant(title="The Example Show", language="en"),
            TitleVariant(title="Die Beispielserie", language="de"),
        ),
        season=2,
        episode=4,
    )

    assert metadata.search_queries(preferred_languages=("en", "es"), limit=2) == (
        "La Serie de Ejemplo S02E04",
        "The Example Show S02E04",
    )


async def test_cinemeta_metadata_is_cached_within_its_ttl():
    requests = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json={
                "meta": {
                    "name": "La Película de Ejemplo",
                    "originalTitle": "The Example Film",
                    "releaseInfo": "2026",
                }
            },
        )

    client = CinemetaClient(base_url="https://cinemeta.example", metadata_ttl_seconds=60)
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://cinemeta.example/", transport=httpx.MockTransport(handle)
    )
    try:
        first = await client.resolve("movie", "tt1234567")
        second = await client.resolve("movie", "tt1234567")
    finally:
        await client.close()

    assert requests == 1
    assert first == second
    assert first.aliases == (TitleVariant(title="The Example Film"),)
