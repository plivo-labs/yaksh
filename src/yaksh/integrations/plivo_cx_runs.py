"""Reads a Plivo CX agent's record of a test call: the run of the agent's flow that served the
call, from Plivo's public agent API.

An outbound call's run is the `api_id` of the trigger's response. An inbound call's run is
found among the flow's runs that started during the call, by the number Yaksh called from: the
run's call UUID is another leg's, and runs of calls placed together start in the same second.
"""

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from yaksh.diagnostics import describe_exception
from yaksh.domain.agent_records import (
    MAX_TEXT_CHARS,
    MAX_TURNS,
    MAX_VALUE_CHARS,
    AgentRecord,
    CallRef,
    Found,
    Lookup,
    Missing,
    Pending,
    RecordTool,
    RecordTurn,
    SavedValue,
    clip,
)
from yaksh.domain.agents import Direction
from yaksh.domain.conversations import Role
from yaksh.domain.record_sources import RecordProvider, RecordSource
from yaksh.integrations.trigger import EXCERPT_CHARS, address_problem, guarded_session, read_at_most

TIMEOUT = aiohttp.ClientTimeout(total=15, sock_connect=5)
READ_LIMIT = 5 * 1024 * 1024
PAGE_SIZE = 20
MAX_PAGES = 10
MAX_CANDIDATES = 10
WINDOW_MARGIN = timedelta(seconds=5)
RATE_LIMIT_WAIT_S = 60.0
RUNNING = "IN_PROGRESS"
FLOW_ENDED = "FLOW_EXECUTION_COMPLETE"
SETTLE = timedelta(seconds=90)
"""How long after a run's last line and its end its log can still gain lines. Plivo CX writes
lines late: on a live call, a caller line timed before FLOW_EXECUTION_COMPLETE was not in a
read 22 s after the call, and the agent's goodbye was timed after FLOW_EXECUTION_COMPLETE."""
SPEAKERS = {"user": Role.CALLER, "assistant": Role.AGENT}


class Stop(Exception):
    def __init__(self, lookup: Pending | Missing) -> None:
        super().__init__(lookup.reason)
        self.lookup = lookup


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    started_at: datetime | None
    """None for a run still in its queue."""
    ended_at: datetime | None
    playground: bool


class PlivoCxRuns:
    def __init__(self, *, allow_private: bool) -> None:
        self._allow_private = allow_private

    async def find(self, source: RecordSource, headers: Mapping[str, str], call: CallRef) -> Lookup:
        agent_url = str(source.url).rstrip("/")
        problem = address_problem(agent_url, self._allow_private)
        if problem is not None:
            return Missing(problem)
        async with guarded_session(allow_private=self._allow_private, timeout=TIMEOUT) as session:
            api = AgentApi(session, agent_url, dict(headers))
            try:
                if call.direction is Direction.OUTBOUND:
                    return await outbound_run(api, call)
                return await inbound_run(api, call)
            except Stop as stop:
                return stop.lookup
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                return Missing(
                    f"Plivo CX answered in a shape Yaksh does not read: {describe_exception(error)}"
                )


class AgentApi:
    """GET requests to one agent of the Plivo API; an answer that ends the lookup raises Stop."""

    def __init__(self, session: aiohttp.ClientSession, agent_url: str, headers: dict[str, str]):
        self._session = session
        self._agent_url = agent_url
        self._headers = headers

    async def runs(self, offset: int) -> list[RunSummary]:
        page = await self._get(
            f"{self._agent_url}/Run/?limit={PAGE_SIZE}&offset={offset}",
            not_found=Missing("Plivo CX has no agent at this URL (HTTP 404)"),
        )
        return [summary(row) for row in page.get("objects") or []]

    async def run(self, run_id: str) -> dict[str, Any]:
        return await self._get(
            f"{self._agent_url}/Run/{run_id}/",
            not_found=Pending(f"Plivo CX has no run {run_id} yet"),
        )

    async def _get(self, url: str, *, not_found: Pending | Missing) -> dict[str, Any]:
        try:
            async with self._session.get(
                url, headers=self._headers, allow_redirects=False
            ) as response:
                status = response.status
                body, too_large = await read_at_most(response, READ_LIMIT)
                retry_after = response.headers.get("Retry-After")
        except (aiohttp.ClientError, TimeoutError) as error:
            raise Stop(Pending(f"Plivo CX did not answer: {describe_exception(error)}")) from None
        if status == 404:
            raise Stop(not_found)
        if status == 429:
            raise Stop(
                Pending(
                    "Plivo CX allows 60 requests a minute for each Auth ID",
                    retry_after_s=wait_of(retry_after),
                )
            )
        if status in (401, 403):
            raise Stop(Missing(f"Plivo CX refused the agent record's headers (HTTP {status})"))
        if 400 <= status < 500:
            raise Stop(Missing(f"Plivo CX refused the request (HTTP {status}): {excerpt(body)}"))
        if status != 200:
            raise Stop(Pending(f"Plivo CX answered HTTP {status}"))
        if too_large:
            raise Stop(Missing(f"the Plivo CX run is larger than {READ_LIMIT // (1024 * 1024)} MB"))
        try:
            data = json.loads(body)
        except ValueError:
            raise Stop(Missing("Plivo CX answered with something that is not JSON")) from None
        if not isinstance(data, dict):
            raise Stop(Missing("Plivo CX answered with something that is not a JSON object"))
        return data


def excerpt(body: bytes) -> str:
    return body.decode(errors="replace")[:EXCERPT_CHARS]


def wait_of(retry_after: str | None) -> float:
    try:
        return max(float(retry_after or ""), 1.0)
    except ValueError:
        return RATE_LIMIT_WAIT_S


async def outbound_run(api: AgentApi, call: CallRef) -> Lookup:
    run_id = trigger_run_id(call.trigger_response)
    if run_id is None:
        return Missing(
            "the trigger's response has no api_id, so Yaksh cannot tell which Plivo CX run "
            "placed the call"
        )
    detail = await api.run(run_id)
    called = start_call(detail).get("call.to")
    if called is not None and digits(called) != digits(call.yaksh_number):
        return Missing(f"Plivo CX run {run_id} called {called}, not {call.yaksh_number}")
    return finished(detail)


async def inbound_run(api: AgentApi, call: CallRef) -> Lookup:
    earliest, latest = call.started_at - WINDOW_MARGIN, call.ended_at + WINDOW_MARGIN
    window = f"between {call.started_at:%H:%M:%S} and {call.ended_at:%H:%M:%S} UTC"
    candidates = await runs_in_window(api, earliest, latest)
    candidates.sort(key=lambda run: distance(run, call))
    unlogged = []
    for run in candidates[:MAX_CANDIDATES]:
        detail = await api.run(run.run_id)
        caller = start_call(detail).get("call.from")
        if caller is None:
            unlogged.append(run.run_id)
        elif digits(caller) == digits(call.yaksh_number):
            return finished(detail)
    if unlogged:
        return Pending(f"Plivo CX has not logged who called in run {', '.join(unlogged)} yet")
    if len(candidates) > MAX_CANDIDATES:
        return Pending(
            f"none of the {MAX_CANDIDATES} runs of this Plivo CX agent closest to the call came "
            f"from {call.yaksh_number}, and Yaksh does not read the other "
            f"{len(candidates) - MAX_CANDIDATES} that started {window}"
        )
    return Pending(f"no run of this Plivo CX agent came from {call.yaksh_number} {window}")


async def runs_in_window(api: AgentApi, earliest: datetime, latest: datetime) -> list[RunSummary]:
    """The flow's runs that started in the window. The list is newest first, so its pages are
    read until a run started before the window."""
    found: list[RunSummary] = []
    for page in range(MAX_PAGES):
        runs = await api.runs(page * PAGE_SIZE)
        starts = [run.started_at for run in runs if run.started_at is not None]
        found += [
            run
            for run in runs
            if run.started_at is not None
            and earliest <= run.started_at <= latest
            and not run.playground
        ]
        if len(runs) < PAGE_SIZE or (starts and min(starts) < earliest):
            return found
    raise Stop(
        Missing(
            f"the Plivo CX agent has more than {MAX_PAGES * PAGE_SIZE} runs since the call "
            "started, and Yaksh reads no further"
        )
    )


def distance(run: RunSummary, call: CallRef) -> tuple[bool, timedelta]:
    """How far a run's start and end are from the call's: the closest run is read first, and
    a run that has not ended after every run that has, since the call has ended."""
    start = abs((run.started_at or call.connected_at) - call.connected_at)
    if run.ended_at is None:
        return True, start
    return False, start + abs(run.ended_at - call.ended_at)


def summary(row: dict[str, Any]) -> RunSummary:
    return RunSummary(
        run_id=str(row["run_uuid"]),
        started_at=moment(row["started_at"]) if row.get("started_at") else None,
        ended_at=moment(row["ended_at"]) if row.get("ended_at") else None,
        playground=bool(row.get("is_playground")),
    )


def trigger_run_id(response: str | None) -> str | None:
    try:
        data = json.loads(response or "")
    except ValueError:
        return None
    run_id = data.get("api_id") if isinstance(data, dict) else None
    return run_id if isinstance(run_id, str) and run_id else None


def finished(detail: dict[str, Any]) -> Found | Pending:
    record = parse_run(detail, datetime.now(UTC))
    if record.complete:
        return Found(record)
    return Pending(
        f"Plivo CX has not finished run {record.external_id} (status {record.status})", record
    )


def logs_of(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """The run's log entries. A log in another shape raises TypeError, which find() makes a
    missing record: an empty log would read as a call where the agent heard nothing."""
    logs = detail.get("logs")
    if logs is None:
        return []
    if not isinstance(logs, list) or not all(isinstance(entry, dict) for entry in logs):
        raise TypeError("the run's logs are not a list of objects")
    return logs


def start_call(detail: dict[str, Any]) -> dict[str, Any]:
    """The call facts the flow's Start node logged, such as call.from and call.to."""
    for entry in logs_of(detail):
        config = entry.get("node_config")
        if (
            entry.get("event_name") == "NODE_EXECUTED"
            and isinstance(config, dict)
            and ("call.from" in config or "call.to" in config)
        ):
            return config
    return {}


def parse_run(detail: dict[str, Any], now: datetime) -> AgentRecord:
    """A value saved under the same name by two nodes keeps its node in the name, as Plivo
    CX's own hang-up callback names it. The record is final when Plivo CX ended the run and its
    log has settled."""
    logs = logs_of(detail)
    nodes = {
        str(entry.get("node_uuid")): str(entry.get("current_node") or "")
        for entry in logs
        if entry.get("event_name") == "NODE_EXECUTED"
    }
    turns: list[RecordTurn] = []
    tools: list[RecordTool] = []
    saved: dict[tuple[str, str], str] = {}
    for entry in logs:
        at = log_time(entry.get("timestamp"))
        event = entry.get("event_name")
        if event == "NODE_CHUNK_CREATED":
            role = SPEAKERS.get(str(entry.get("sender")))
            text = str(entry.get("text") or "").strip()
            if role is not None and text and len(turns) < MAX_TURNS:
                turns.append(RecordTurn(role=role, text=clip(text, MAX_TEXT_CHARS), at=at))
            config = entry.get("node_config")
            variables = config.get("variables") if isinstance(config, dict) else None
            for name, value in (variables or {}).items():
                saved[(nodes.get(str(entry.get("node_uuid")), ""), str(name))] = shown(value)
        elif event == "SYSTEM_CHUNK_CREATED" and entry.get("type") == "TOOL_CALL_EVENT":
            response = entry.get("tool_response")
            tools.append(
                RecordTool(
                    name=str(entry.get("tool_name") or ""),
                    arguments=clip(json.dumps(entry.get("tool_input") or {}), MAX_TEXT_CHARS),
                    output=None if response is None else clip(str(response), MAX_TEXT_CHARS),
                    failed=bool(entry.get("tool_call_error")),
                    at=at,
                )
            )
    status = str(detail.get("status") or "")
    times = [time for entry in logs if (time := log_time(entry.get("timestamp"))) is not None]
    if detail.get("ended_at"):
        times.append(moment(str(detail["ended_at"])))
    settled = bool(times) and now >= max(times) + SETTLE
    ended = status != RUNNING and any(entry.get("event_name") == FLOW_ENDED for entry in logs)
    return AgentRecord(
        provider=RecordProvider.PLIVO_CX,
        external_id=str(detail.get("run_uuid") or ""),
        status=status,
        complete=ended and settled,
        turns=turns,
        saved=saved_values(saved),
        tools=tools,
    )


def saved_values(saved: dict[tuple[str, str], str]) -> list[SavedValue]:
    nodes_of: defaultdict[str, set[str]] = defaultdict(set)
    for node, name in saved:
        nodes_of[name].add(node)
    return [
        SavedValue(
            name=f"{node}.{name}" if len(nodes_of[name]) > 1 else name,
            value=clip(value, MAX_VALUE_CHARS),
        )
        for (node, name), value in saved.items()
    ]


def shown(value: object) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def log_time(value: object) -> datetime | None:
    """Plivo CX writes log times in UTC without a zone."""
    try:
        return moment(value) if isinstance(value, str) else None
    except ValueError:
        return None


def moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def digits(number: object) -> str:
    return "".join(char for char in str(number) if char.isdigit())
