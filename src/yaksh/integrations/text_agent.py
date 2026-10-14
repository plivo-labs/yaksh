"""The text contract: one HTTP request a turn to a text agent, and its reply read back.

The first request starts a session and the reply names it; each later request carries that
session id. docs/content/docs/text-tests.mdx is the contract for agent builders.
"""

import json
from dataclasses import dataclass
from typing import Any

import aiohttp

from yaksh.diagnostics import describe_exception
from yaksh.domain.agents import TEXT_TURN_TIMEOUT_S
from yaksh.domain.conversations import ToolItem
from yaksh.domain.scenarios import Fact
from yaksh.integrations.trigger import (
    EXCERPT_CHARS,
    address_problem,
    guarded_session,
    mask,
    read_at_most,
)

CONTRACT_VERSION = "1"
REPLY_LIMIT = 256 * 1024
RETRYABLE_4XX = frozenset({408, 410, 425, 429})
"""Client errors that a later attempt can pass; any other 4xx on the first request means the
agent's URL or headers are wrong."""


class TextAgentError(Exception):
    def __init__(self, detail: str, *, refused: bool = False, lost: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.refused = refused
        """The agent refused to start: trying again with the same settings fails the same way."""
        self.lost = lost
        """The agent no longer knows the session (HTTP 410)."""


@dataclass(frozen=True)
class AgentReply:
    session_id: str | None
    """Only on the first reply."""
    text: str
    tools: list[ToolItem]
    ended: bool


class TextAgent:
    """The HTTP side of one conversation with a text agent. Each request is sent once."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str],
        secrets: tuple[str, ...],
        *,
        conversation_id: str,
        allow_private: bool,
    ) -> None:
        self._url = url
        self._headers = {
            **headers,
            "Content-Type": "application/json",
            "Yaksh-Contract": CONTRACT_VERSION,
            "Yaksh-Conversation-Id": conversation_id,
        }
        self._secrets = secrets
        self._allow_private = allow_private
        self._session = guarded_session(
            allow_private=allow_private,
            timeout=aiohttp.ClientTimeout(total=TEXT_TURN_TIMEOUT_S, sock_connect=5),
        )

    async def start(self, message: str, modality: str, custom_data: list[Fact]) -> AgentReply:
        problem = address_problem(self._url, self._allow_private)
        if problem is not None:
            raise TextAgentError(problem, refused=True)
        body = {
            "message": message,
            "modality": modality,
            "customData": {fact.name: fact.value for fact in custom_data},
        }
        return await self._send(body, first=True)

    async def turn(self, session_id: str, message: str) -> AgentReply:
        return await self._send({"sessionId": session_id, "message": message}, first=False)

    async def close(self, session_id: str, reason: str, timeout_s: float) -> None:
        """Tell the agent the conversation ended; best effort, the reply is not read."""
        body = {"sessionId": session_id, "status": "ended", "reason": reason}
        try:
            async with self._session.post(
                self._url,
                json=body,
                headers=self._headers,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
            ):
                pass
        except aiohttp.ClientError, TimeoutError:
            return

    async def aclose(self) -> None:
        await self._session.close()

    async def _send(self, body: dict[str, Any], *, first: bool) -> AgentReply:
        try:
            async with self._session.post(
                self._url, json=body, headers=self._headers, allow_redirects=False
            ) as response:
                status = response.status
                raw, too_large = await read_at_most(response, REPLY_LIMIT)
        except (aiohttp.ClientError, TimeoutError) as error:
            raise TextAgentError(self.masked(describe_exception(error))) from None
        if not 200 <= status < 300:
            excerpt = self.masked(raw.decode(errors="replace"))[:EXCERPT_CHARS]
            if status == 410:
                raise TextAgentError(f"the agent lost the session (HTTP 410): {excerpt}", lost=True)
            refused = first and 400 <= status < 500 and status not in RETRYABLE_4XX
            raise TextAgentError(f"HTTP {status}: {excerpt}", refused=refused)
        if too_large:
            raise TextAgentError(f"invalid reply: longer than {REPLY_LIMIT // 1024} KiB")
        try:
            return self._reply(raw, first=first)
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            raise TextAgentError(f"invalid reply: {self.masked(str(error))}") from None

    def masked(self, text: str) -> str:
        """The text with its secrets hidden, safe to store: no NUL, and no lone surrogate (the
        encode raises), both of which Postgres refuses."""
        return mask(text.encode().decode().replace("\x00", ""), self._secrets)

    def _reply(self, raw: bytes, *, first: bool) -> AgentReply:
        data = json.loads(raw)
        session_id = data.get("sessionId") if first else None
        if first and not (isinstance(session_id, str) and 1 <= len(session_id) <= 255):
            raise ValueError("the first reply needs a sessionId of 1 to 255 characters")
        words: list[str] = []
        tools: dict[str, ToolItem] = {}
        for item in data["messages"]:
            if item["role"] == "assistant":
                words.append(item.get("content") or "")
                for call in item.get("tool_calls") or []:
                    function = call["function"]
                    tools[call["id"]] = ToolItem(
                        id=self.masked(call["id"]),
                        name=self.masked(function["name"]),
                        arguments=self.masked(function["arguments"]),
                    )
            elif item["role"] == "tool" and item["tool_call_id"] in tools:
                called = tools[item["tool_call_id"]]
                tools[item["tool_call_id"]] = called.model_copy(
                    update={"output": self.masked(item["content"])}
                )
        return AgentReply(
            session_id=session_id,
            text=self.masked(" ".join(word.strip() for word in words if word.strip())),
            tools=list(tools.values()),
            ended=data.get("status") == "ended",
        )
