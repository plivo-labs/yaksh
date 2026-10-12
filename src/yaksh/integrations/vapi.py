"""Reads of a Vapi organization's assistants, tools and numbers with its own key, to import
assistants."""

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

import aiohttp

from yaksh.diagnostics import describe_exception
from yaksh.domain.agent_import import VAPI_PAGE_SIZE, VapiRegion
from yaksh.domain.errors import ProviderCallError

REGION_APIS: dict[VapiRegion, str] = {
    VapiRegion.US: "https://api.vapi.ai",
    VapiRegion.EU: "https://api.eu.vapi.ai",
}
TIMEOUT = aiohttp.ClientTimeout(total=10)


class VapiError(ProviderCallError):
    pass


class VapiApi:
    def __init__(self, api_key: str, *, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def list_assistants(self, *, created_before: datetime | None) -> list[dict[str, Any]]:
        params = {"limit": str(VAPI_PAGE_SIZE)}
        if created_before is not None:
            params["createdAtLt"] = created_before.isoformat()
        return await self._list("/assistant", params, "listing assistants")

    async def get_assistant(self, assistant_id: str) -> dict[str, Any]:
        return await self._object(
            f"/assistant/{quote(assistant_id, safe='')}", "reading the assistant"
        )

    async def get_tool(self, tool_id: str) -> dict[str, Any]:
        return await self._object(f"/tool/{quote(tool_id, safe='')}", "reading a tool")

    async def phone_numbers(self) -> list[dict[str, Any]]:
        """Every number, page by page: an assistant's own number can be on any page."""
        numbers: list[dict[str, Any]] = []
        params = {"limit": str(VAPI_PAGE_SIZE)}
        while True:
            page = await self._list("/phone-number", params, "listing numbers")
            numbers += page
            created = page[-1].get("createdAt") if len(page) == VAPI_PAGE_SIZE else None
            if not isinstance(created, str):
                return numbers
            params = {**params, "createdAtLt": created}

    async def _object(self, path: str, doing: str) -> dict[str, Any]:
        found = await self._get(path, {}, doing)
        if not isinstance(found, dict):
            raise ValueError(f"{doing} answered with a body that is not an object")
        return found

    async def _list(self, path: str, params: dict[str, str], doing: str) -> list[dict[str, Any]]:
        found = await self._get(path, params, doing)
        if not isinstance(found, list):
            raise ValueError(f"{doing} answered with a body that is not a list")
        return [item for item in found if isinstance(item, dict)]

    async def _get(self, path: str, params: dict[str, str], doing: str) -> Any:
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.get(f"{self.base_url}{path}", params=params) as response,
            ):
                status, body = response.status, await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as error:
            raise VapiError(f"{doing} did not reach Vapi: {describe_exception(error)}") from error
        if status >= 400:
            raise VapiError(f"{doing} failed with {status}: {body[:200]}", status=status)
        return json.loads(body)
