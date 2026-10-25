"""The caller for a text agent: the persona's model writes each line, and the text contract
carries it to the agent, one request a turn, with no audio."""

import asyncio
import json
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any

import openai
from openai import AsyncOpenAI
from openai.types.responses import EasyInputMessageParam, FunctionToolParam, Response

from yaksh.caller.audio import Clock
from yaksh.caller.pipeline import (
    END_CALL,
    IDLE_NUDGES,
    SILENT_END,
    CallState,
    Silence,
)
from yaksh.config import Settings
from yaksh.diagnostics import describe_exception
from yaksh.domain.conversations import (
    CallerSettings,
    CallerUsage,
    CallObserver,
    CallOutcome,
    CallRequest,
    EndReason,
    Role,
    Turn,
    WireEvent,
    WireEventKind,
)
from yaksh.domain.triggers import Filler, RenderError
from yaksh.integrations.openai_models import caller_effort, failure
from yaksh.integrations.text_agent import AgentReply, TextAgent, TextAgentError
from yaksh.timings import TIMINGS

log = logging.getLogger(__name__)

MODALITY = "audio"
"""Text agents are voice agents tested over text: they keep their voice prompts and rules."""
LLM_TIMEOUT_S = 60.0
CLOSE_LIMIT_S = 3.0
CLOSE_REASONS: dict[EndReason | None, str] = {
    EndReason.CALLER_HANGUP: "caller_hangup",
    EndReason.TURN_LIMIT: "turn_limit",
    EndReason.AGENT_SILENT: "agent_silent",
    EndReason.USER_REQUEST: "stopped",
}
END_CALL_TOOL = FunctionToolParam(
    type="function",
    name=END_CALL.name,
    description=END_CALL.description,
    parameters=END_CALL.to_default_dict()["parameters"],
    strict=False,
)


def reasoning(model: str, effort: str | None) -> dict[str, Any]:
    """The phone caller's effort, so both callers ask the model the same way."""
    effort = caller_effort(model, effort)
    return {"reasoning": {"effort": effort}} if effort else {}


@dataclass(frozen=True)
class Line:
    """A line for the caller to say, before it is sent."""

    text: str
    started_at_ms: int
    scripted: bool = False
    ends: str | None = None
    """The caller model's reason, when this line ends the call."""


class Stopped(Exception):
    """The worker asked the call to stop while Yaksh waited for the agent or the model."""


async def until_stop[T](stop: asyncio.Event, work: Awaitable[T]) -> T:
    """The result of `work`, or Stopped as soon as `stop` is set. On every exit, cancellation
    too, no task of it is left running."""
    task = asyncio.ensure_future(work)
    waiter = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            return task.result()
        raise Stopped
    finally:
        for child in (task, waiter):
            child.cancel()
        await asyncio.gather(task, waiter, return_exceptions=True)


class TextCaller:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(
        self, request: CallRequest, observer: CallObserver, stop: asyncio.Event
    ) -> CallOutcome:
        assert request.agent.endpoint is not None
        secrets = {
            name: value.get_secret_value()
            for name, value in request.app_settings.secrets.triggers.items()
        }
        filler = Filler(
            number=None,
            conversation_id=str(request.conversation_id),
            agent_data=request.agent_data,
            secrets=secrets,
        )
        try:
            headers = filler.headers(request.agent.endpoint.headers)
        except RenderError as error:
            return CallOutcome(
                connected=False, end_reason=EndReason.START_REFUSED, caller_error=str(error)
            )
        llm_key = request.app_settings.secrets.llm_api_key
        assert llm_key is not None, "a text run starts only with the LLM provider key"
        agent = TextAgent(
            str(request.agent.endpoint.url),
            headers,
            tuple(filler.carried),
            conversation_id=str(request.conversation_id),
            allow_private=self._settings.allow_private_hosts,
        )
        model = AsyncOpenAI(
            api_key=llm_key.get_secret_value(),
            base_url=request.app_settings.llm.base_url,
            timeout=LLM_TIMEOUT_S,
            max_retries=1,
        )
        conversation = TextConversation(request, observer, stop, agent, model)
        try:
            return await conversation.run(close_s=min(CLOSE_LIMIT_S, TIMINGS.end_timeout_s / 2))
        finally:
            await agent.aclose()
            await model.close()


class TextConversation:
    """One conversation: the first request starts the agent's session, then the caller and the
    agent take turns until one of them ends it, a limit is reached, or the worker stops it."""

    def __init__(
        self,
        request: CallRequest,
        observer: CallObserver,
        stop: asyncio.Event,
        agent: TextAgent,
        model: AsyncOpenAI,
    ) -> None:
        self._request = request
        self._observer = observer
        self._stop = stop
        self._agent = agent
        self._model = model
        self._clock = Clock()
        self._state = CallState()
        self._history: list[EasyInputMessageParam] = []
        self._usage: dict[str, int] = {}
        self._session_id: str | None = None
        self._agent_closed = False
        self._connected_ms: int | None = None

    async def run(self, close_s: float) -> CallOutcome:
        try:
            await self._converse()
        except Stopped:
            self._state.end(EndReason.USER_REQUEST)
        except TextAgentError as error:
            self._fail(error.detail, refused=error.refused and self._session_id is None)
            if error.lost:
                self._session_id = None
        except openai.OpenAIError as error:
            self._fail(f"the caller's model failed: {failure(error)}")
        except asyncio.CancelledError:
            self._state.end(EndReason.USER_REQUEST)
            await self._close(close_s)
            raise
        except Exception as error:
            log.exception("text caller failed for conversation %s", self._request.conversation_id)
            self._fail(describe_exception(error))
        ended_ms = self._clock.ms()
        await self._close(close_s)
        connected = self._connected_ms is not None
        return CallOutcome(
            connected=connected,
            end_reason=self._state.end_reason or EndReason.ERROR,
            caller_error=self._state.error,
            caller_reason=self._state.caller_reason,
            talk_ms=ended_ms - self._connected_ms if self._connected_ms is not None else None,
            caller_settings=CallerSettings(
                llm_model=self._request.caller.model,
                reasoning_effort=caller_effort(
                    self._request.caller.model, self._request.caller.reasoning_effort
                ),
                scenario_model=self._request.scenario_model,
            ),
            caller_usage=CallerUsage.model_validate(self._usage),
        )

    async def _close(self, timeout_s: float) -> None:
        """Free the agent's session, unless the agent ended it or never made one."""
        if self._session_id is not None and not self._agent_closed:
            await self._agent.close(self._session_id, self._close_reason(), timeout_s)

    def _fail(self, detail: str, *, refused: bool = False) -> None:
        self._state.blame(detail)
        self._state.end(EndReason.START_REFUSED if refused else EndReason.ERROR)

    def _close_reason(self) -> str:
        return CLOSE_REASONS.get(self._state.end_reason, "error")

    async def _converse(self) -> None:
        request = self._request
        speaks_first = request.agent.agent_speaks_first
        reply = await self._start(None if speaks_first else self._fixed(request.first_words))
        silence = Silence(IDLE_NUDGES)
        answered = 0
        while not reply.ended:
            if not reply.text:
                if silence.give_up():
                    self._state.end(EndReason.AGENT_SILENT)
                    return
                reply = await self._send(self._fixed(request.nudge))
                continue
            silence.heard()
            if answered == request.max_turns:
                self._mark(WireEventKind.TURN_LIMIT)
                await self._send(self._fixed(request.goodbye))
                self._state.end(EndReason.TURN_LIMIT)
                return
            line = await self._caller_line()
            answered += 1
            reply = await self._send(line)
            if line.ends is not None:
                if self._state.end(EndReason.CALLER_HANGUP):
                    self._state.caller_reason = line.ends
                    self._mark(WireEventKind.END_CALL, line.ends)
                return
        self._state.end(EndReason.AGENT_HANGUP)

    def _fixed(self, text: str) -> Line:
        """Fixed text Yaksh says for the caller, such as the idle nudge, without the model."""
        return Line(text, self._clock.ms(), scripted=True)

    async def _start(self, line: Line | None) -> AgentReply:
        """Start the agent's session; the caller's first words go with it when it speaks
        first."""
        sent = self._clock.ms()
        reply = await until_stop(
            self._stop,
            self._agent.start(
                "" if line is None else line.text, MODALITY, self._request.agent_data
            ),
        )
        self._session_id = reply.session_id
        self._connected_ms = sent
        self._mark(WireEventKind.CONNECTED, self._agent.masked(reply.session_id or ""), at_ms=sent)
        if line is not None:
            self._caller_says(line)
        self._agent_says(reply, sent)
        return reply

    async def _send(self, line: Line) -> AgentReply:
        """Send the caller's line; it joins the transcript only once the agent has it."""
        assert self._session_id is not None
        sent = self._clock.ms()
        reply = await until_stop(self._stop, self._agent.turn(self._session_id, line.text))
        self._caller_says(line)
        self._agent_says(reply, sent)
        return reply

    async def _caller_line(self) -> Line:
        """The caller's next line from its model, with the model's reason when the line ends the
        call. A model that ends the call without a word gets one more reply to speak in; after
        that, Yaksh says the goodbye itself."""
        retried = False
        while True:
            started = self._clock.ms()
            response = await until_stop(self._stop, self._ask(retried))
            words = response.output_text.strip()
            ended = next((item for item in response.output if item.type == "function_call"), None)
            if ended is None:
                if words:
                    return Line(words, started)
                raise RuntimeError("the caller's model answered with no words and no tool call")
            if not words and not retried:
                retried = True
                log.info(
                    "caller tried to end conversation %s without a word",
                    self._request.conversation_id,
                )
                continue
            reason = str(json.loads(ended.arguments or "{}").get("reason") or "")
            if words:
                return Line(words, started, ends=reason)
            return Line(self._request.goodbye, self._clock.ms(), scripted=True, ends=reason)

    async def _ask(self, silent_end: bool) -> Response:
        extra = [EasyInputMessageParam(role="developer", content=SILENT_END)] if silent_end else []
        response = await self._model.responses.create(
            model=self._request.caller.model,
            instructions=self._request.instructions,
            input=[*self._history, *extra],
            tools=[END_CALL_TOOL],
            parallel_tool_calls=False,
            store=False,
            extra_body=reasoning(self._request.caller.model, self._request.caller.reasoning_effort),
        )
        self._count(response)
        return response

    def _count(self, response: Response) -> None:
        usage = response.usage
        if usage is None:
            return
        counts = {
            "llm_prompt_tokens": usage.input_tokens,
            "llm_completion_tokens": usage.output_tokens,
            "llm_reasoning_tokens": usage.output_tokens_details.reasoning_tokens,
            "llm_cache_read_tokens": usage.input_tokens_details.cached_tokens,
        }
        for field, value in counts.items():
            self._usage[field] = self._usage.get(field, 0) + (value or 0)

    def _agent_says(self, reply: AgentReply, sent_ms: int) -> None:
        self._agent_closed = reply.ended
        if reply.text:
            self._history.append(EasyInputMessageParam(role="user", content=reply.text))
        if reply.text or reply.tools:
            self._observer.turn(
                Turn(
                    role=Role.AGENT,
                    text=reply.text,
                    started_at_ms=sent_ms,
                    ended_at_ms=self._clock.ms(),
                    tools=reply.tools,
                )
            )

    def _caller_says(self, line: Line) -> None:
        self._history.append(EasyInputMessageParam(role="assistant", content=line.text))
        self._observer.turn(
            Turn(
                role=Role.CALLER,
                text=line.text,
                started_at_ms=line.started_at_ms,
                ended_at_ms=self._clock.ms(),
                scripted=line.scripted,
            )
        )

    def _mark(
        self, kind: WireEventKind, detail: str | None = None, at_ms: int | None = None
    ) -> None:
        at = self._clock.ms() if at_ms is None else at_ms
        self._observer.wire_event(WireEvent(kind=kind, at_ms=at, detail=detail))
