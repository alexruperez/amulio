import asyncio
import os

import httpx
import pytest

from amulio.amule_api import AmuleApiClient
from amulio.models import Candidate
from amulio.tokens import sign

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_completed_shared_file_is_re_resolved_and_streamed():
    base_url = os.environ.get("AMULIO_INTEGRATION_URL")
    if base_url is None:
        pytest.skip("Set AMULIO_INTEGRATION_URL after starting tests/integration/compose.yaml")

    api = AmuleApiClient(
        base_url=os.environ.get("AMULE_API_INTEGRATION_URL", "http://127.0.0.1:14713/api/v0"),
        admin_password="fixture-admin-password",
    )
    try:
        for _ in range(30):
            shared_files = await api.shared_files()
            fixture = next(
                (item for item in shared_files if item.get("name") == "amulio-fixture.mp4"), None
            )
            if fixture is not None:
                break
            await asyncio.sleep(1)
        else:
            raise AssertionError("aMule did not share the legal aMulio fixture video")
        shared = await api.shared_file(fixture["hash"])
        assert shared is not None
        assert shared.path == "/data/incoming"

        candidate = Candidate(
            hash=shared.hash,
            name=shared.name,
            size=shared.size,
            ed2k_link=f"ed2k://|file|{shared.name}|{shared.size}|{shared.hash}|/",
        )
        token = sign(
            {"candidate": candidate.model_dump()},
            secret="integration-token-secret-000000000000000000000000",
            ttl_seconds=60,
        )
        async with httpx.AsyncClient(base_url=base_url, follow_redirects=True) as client:
            response = await client.get(f"/play/{token}")
    finally:
        await api.close()

    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) == candidate.size
