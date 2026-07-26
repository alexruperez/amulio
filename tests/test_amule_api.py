import json

import httpx

from amulio.amule_api import AmuleApiClient


async def test_stop_search_closes_the_specific_remote_search():
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "token"})
        return httpx.Response(200, json={"ok": True})

    client = AmuleApiClient(base_url="https://amuleapi.example/api/v0", admin_password="password")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://amuleapi.example/api/v0/", transport=httpx.MockTransport(handle)
    )
    try:
        await client.stop_search(42)
    finally:
        await client.close()

    assert requests[-1].method == "POST"
    assert requests[-1].url.path == "/api/v0/search/stop"
    assert json.loads(requests[-1].content) == {"search_id": 42, "close": True}
