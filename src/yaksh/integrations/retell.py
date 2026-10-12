"""Reads of a Retell workspace's agents, response engines and numbers with its own key, to
import agents."""

import json
from typing import Any
from urllib.parse import quote

import aiohttp

from yaksh.diagnostics import describe_exception
from yaksh.domain.agent_import import RETELL_PAGE_SIZE
from yaksh.domain.errors import ProviderCallError

RETELL_API = "https://api.retellai.com"
TIMEOUT = aiohttp.ClientTimeout(total=10)
VOICE = {"type": "string", "op": "eq", "value": "voice"}


class RetellError(ProviderCallError):
    pass


class RetellApi:
    def __init__(self, api_key: str, *, base_url: str = RETELL_API) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def list_agents(self, *, cursor: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"filter_criteria": {"channel": VOICE}, "limit": RETELL_PAGE_SIZE}
        if cursor:
            body["pagination_key"] = cursor
        return await self._object("POST", "/v2/list-agents", {}, body, "listing agents")

    async def agent_versions(self, agent_id: str) -> list[dict[str, Any]]:
        return await self._pages(
            f"/list-agent-versions/{quote(agent_id, safe='')}",
            {"limit": "1000"},
            "listing versions",
        )

    async def get_agent(self, agent_id: str, version: int) -> dict[str, Any]:
        return await self._object(
            "GET",
            f"/get-agent/{quote(agent_id, safe='')}",
            {"version": str(version)},
            None,
            "reading the agent",
        )

    async def get_retell_llm(self, llm_id: str, version: int | None) -> dict[str, Any]:
        return await self._object(
            "GET", f"/get-retell-llm/{quote(llm_id, safe='')}", at(version), None, "reading the LLM"
        )

    async def get_conversation_flow(self, flow_id: str, version: int | None) -> dict[str, Any]:
        return await self._object(
            "GET",
            f"/get-conversation-flow/{quote(flow_id, safe='')}",
            at(version),
            None,
            "reading the conversation flow",
        )

    async def phone_numbers(self) -> list[dict[str, Any]]:
        """Every number: an agent's own number can be on any page."""
        return await self._pages("/v2/list-phone-numbers", {}, "listing numbers")

    async def _pages(self, path: str, params: dict[str, str], doing: str) -> list[dict[str, Any]]:
        """Every item of a list that Retell pages with pagination_key."""
        items: list[dict[str, Any]] = []
        while True:
            page = await self._object("GET", path, params, None, doing)
            items += [item for item in page.get("items") or [] if isinstance(item, dict)]
            key = page.get("pagination_key")
            if not page.get("has_more") or not isinstance(key, str):
                return items
            params = {**params, "pagination_key": key}

    async def _object(
        self, method: str, path: str, params: dict[str, str], body: Any, doing: str
    ) -> dict[str, Any]:
        found = await self._call(method, path, params, body, doing)
        if not isinstance(found, dict):
            raise ValueError(f"{doing} answered with a body that is not an object")
        return found

    async def _call(
        self, method: str, path: str, params: dict[str, str], body: Any, doing: str
    ) -> Any:
        try:
            async with (
                aiohttp.ClientSession(headers=self._headers, timeout=TIMEOUT) as session,
                session.request(
                    method, f"{self.base_url}{path}", params=params, json=body
                ) as response,
            ):
                status, text = response.status, await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as error:
            raise RetellError(
                f"{doing} did not reach Retell: {describe_exception(error)}"
            ) from error
        if status >= 400:
            raise RetellError(f"{doing} failed with {status}: {text[:200]}", status=status)
        return json.loads(text)


def at(version: int | None) -> dict[str, str]:
    return {} if version is None else {"version": str(version)}
