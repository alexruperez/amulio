import json

import httpx
import pytest

from amulio.amule_api import AmuleApiClient, AmuleApiError


@pytest.fixture
async def api_client():
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "token"})
        if request.method == "PATCH":
            return httpx.Response(200, json={"results": [{"id": "a" * 32, "ok": True}]})
        if request.method == "DELETE":
            return httpx.Response(200, json={"results": [{"id": "a" * 32, "ok": True}]})
        return httpx.Response(200, json={"downloads": []})

    client = AmuleApiClient(base_url="https://amuleapi.example/api/v0", admin_password="password")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://amuleapi.example/api/v0/", transport=httpx.MockTransport(handle)
    )
    yield client, requests
    await client.close()


async def test_pause_resume_and_cancel_use_bulk_v0_lifecycle_endpoints(api_client):
    client, requests = api_client
    hashes = ["a" * 32]

    assert await client.pause_downloads(hashes) == [{"id": "a" * 32, "ok": True}]
    assert await client.resume_downloads(hashes) == [{"id": "a" * 32, "ok": True}]
    assert await client.cancel_downloads(hashes) == [{"id": "a" * 32, "ok": True}]

    mutations = [request for request in requests if request.method in {"PATCH", "DELETE"}]
    assert [request.method for request in mutations] == ["PATCH", "PATCH", "DELETE"]
    assert [request.url.path for request in mutations] == ["/api/v0/downloads"] * 3
    assert json.loads(mutations[0].content) == {"hashes": hashes, "status": "paused"}
    assert json.loads(mutations[1].content) == {"hashes": hashes, "status": "resumed"}
    assert json.loads(mutations[2].content) == {"hashes": hashes}


async def test_lifecycle_mutations_reject_an_invalid_amuleapi_envelope():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "token"})
        return httpx.Response(200, json={"ok": True})

    client = AmuleApiClient(base_url="https://amuleapi.example/api/v0", admin_password="password")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://amuleapi.example/api/v0/", transport=httpx.MockTransport(handle)
    )
    with pytest.raises(AmuleApiError, match="mutation results"):
        await client.cancel_downloads(["a" * 32])
    await client.close()


async def test_reload_shared_files_uses_the_v0_shared_reload_endpoint(api_client):
    client, requests = api_client

    await client.reload_shared_files()

    reload_requests = [
        request
        for request in requests
        if request.method == "POST" and request.url.path.endswith("/shared/reload")
    ]
    assert len(reload_requests) == 1
    assert reload_requests[0].url.path == "/api/v0/shared/reload"
