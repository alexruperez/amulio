import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from amulio.models import AmuleFile, AmuleSearchResult


class AmuleApiError(RuntimeError):
    pass


class AmuleApiClient:
    def __init__(self, *, base_url: str, admin_password: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", timeout=20)
        self._admin_password = admin_password
        self._token: str | None = None
        self._login_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def _login(self) -> str:
        async with self._login_lock:
            if self._token:
                return self._token
            response = await self._client.post(
                "auth/login?type=bearer", json={"password": self._admin_password}
            )
            if response.is_error:
                raise AmuleApiError(f"amuleapi login failed ({response.status_code})")
            token = response.json().get("token")
            if not isinstance(token, str) or not token:
                raise AmuleApiError("amuleapi login response did not include a bearer token")
            self._token = token
            return token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._login()
        response = await self._client.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        if response.status_code == 401:
            self._token = None
            token = await self._login()
            response = await self._client.request(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
        if response.is_error:
            detail = response.text[:200]
            raise AmuleApiError(
                f"amuleapi {method} {path} failed ({response.status_code}): {detail}"
            )
        return response

    async def health(self) -> dict[str, Any]:
        return (await self._request("GET", "status")).json()

    async def start_search(self, query: str, *, kind: str = "global") -> int:
        response = await self._request("POST", "search", json={"query": query, "type": kind})
        search_id = response.json().get("search_id")
        if not isinstance(search_id, int):
            raise AmuleApiError("amuleapi search response did not include search_id")
        return search_id

    async def search_results(self, search_id: int) -> list[AmuleSearchResult]:
        response = await self._request("GET", "search/results", params={"search_id": search_id})
        results = response.json().get("results", [])
        return [AmuleSearchResult.model_validate(item) for item in results]

    async def stop_search(self, search_id: int, *, close: bool = True) -> None:
        await self._request("POST", "search/stop", json={"search_id": search_id, "close": close})

    async def add_download(self, ed2k_link: str) -> None:
        await self._request("POST", "downloads", json={"ed2k_link": ed2k_link})

    async def shared_file(self, file_hash: str) -> AmuleFile | None:
        response = await self._client.get(
            f"shared/{file_hash}", headers={"Authorization": f"Bearer {await self._login()}"}
        )
        if response.status_code == 404:
            return None
        if response.is_error:
            raise AmuleApiError(f"amuleapi shared lookup failed ({response.status_code})")
        result = AmuleFile.model_validate(response.json())
        return None if result.path == "[PartFile]" else result

    async def completed_download(self, file_hash: str) -> AmuleFile | None:
        response = await self._client.get(
            f"downloads/{file_hash}", headers={"Authorization": f"Bearer {await self._login()}"}
        )
        if response.status_code == 404:
            return None
        if response.is_error:
            raise AmuleApiError(f"amuleapi download lookup failed ({response.status_code})")
        result = AmuleFile.model_validate(response.json())
        return result if result.status == "completed" else None

    async def events(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield amuleapi SSE frames for downloads and shared files."""
        token = await self._login()
        async with self._client.stream(
            "GET",
            "events",
            params={"channels": "downloads,shared"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=None,
        ) as response:
            if response.is_error:
                raise AmuleApiError(f"amuleapi events failed ({response.status_code})")
            event_name = "message"
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if not line:
                    if data_lines:
                        try:
                            data = json.loads("\n".join(data_lines))
                        except json.JSONDecodeError:
                            data = None
                        if isinstance(data, dict):
                            yield event_name, data
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").lstrip())
