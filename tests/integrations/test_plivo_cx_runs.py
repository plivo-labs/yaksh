import asyncio
import copy
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response

from yaksh.caller.plivo_server import PlivoServer
from yaksh.domain.agent_records import CallRef, Found, Missing, Pending
from yaksh.domain.agents import Direction
from yaksh.domain.conversations import Role
from yaksh.domain.record_sources import RecordProvider, RecordSource
from yaksh.domain.triggers import Header
from yaksh.integrations.plivo_cx_runs import MAX_CANDIDATES, PlivoCxRuns

FLOW = "c2a36ee8-4f8b-4d56-8b5f-0173ef11ff8a"
AGENT_PATH = f"/v1/Account/MAXXXXXXXXXXXXXXXXXX/AgentFlow/{FLOW}"
LIVE_RUN = json.loads((Path(__file__).parent / "fixtures" / "plivo_cx_run.json").read_text())
YAKSH = "+15550100001"
"""The number the live run's call came from: Yaksh's test number."""
CALL_START = datetime(2026, 10, 23, 12, 28, 24, tzinfo=UTC)


@dataclass
class Cx:
    """A stand-in for the agent API of Plivo CX: its runs, newest first, and their details."""

    url: str = ""
    summaries: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, dict[str, Any]] = field(default_factory=dict)
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    read: list[str] = field(default_factory=list)
    """Each run detail read, in order."""
    auth: list[str] = field(default_factory=list)
    arrived: list[float] = field(default_factory=list)
    """When each request came, by the event loop's clock."""

    def add(self, detail: dict[str, Any]) -> None:
        self.details[detail["run_uuid"]] = detail
        self.summaries.insert(
            0,
            {
                key: detail[key]
                for key in ("run_uuid", "status", "started_at", "ended_at", "is_playground")
            },
        )


@pytest.fixture
async def cx() -> AsyncIterator[Cx]:
    app = FastAPI()
    state = Cx()

    @app.get(f"{AGENT_PATH}/Run/")
    async def runs(request: Request, limit: int, offset: int) -> Response:
        state.arrived.append(asyncio.get_running_loop().time())
        state.auth.append(request.headers.get("authorization", ""))
        if state.status != 200:
            return Response("{}", status_code=state.status, headers=state.headers)
        page = state.summaries[offset : offset + limit]
        return Response(json.dumps({"api_id": "list", "meta": {}, "objects": page}))

    @app.get(f"{AGENT_PATH}/Run/{{run_id}}/")
    async def run(run_id: str) -> Response:
        state.arrived.append(asyncio.get_running_loop().time())
        state.read.append(run_id)
        if state.status != 200:
            return Response("{}", status_code=state.status, headers=state.headers)
        if run_id not in state.details:
            return Response('{"error": "Run not found"}', status_code=404)
        return Response(json.dumps(state.details[run_id]))

    server = PlivoServer(app, port=0)
    await server.start()
    state.url = f"http://127.0.0.1:{server.port}{AGENT_PATH}/"
    yield state
    await server.stop(2.0)


def source(cx: Cx) -> RecordSource:
    return RecordSource(
        provider=RecordProvider.PLIVO_CX,
        url=cx.url,
        headers=[Header(name="Authorization", value="Basic {{secrets.PLIVO_CX_AUTH}}")],
    )


def call(direction: Direction = Direction.INBOUND, trigger: str | None = None) -> CallRef:
    return CallRef(
        direction=direction,
        yaksh_number=YAKSH,
        started_at=CALL_START,
        connected_at=CALL_START + timedelta(seconds=2),
        ended_at=CALL_START + timedelta(seconds=51),
        trigger_response=trigger,
    )


def run_like_live(run_id: str, caller: str, started: str, ended: str) -> dict[str, Any]:
    detail = copy.deepcopy(LIVE_RUN)
    detail.update(run_uuid=run_id, started_at=started, ended_at=ended)
    detail["logs"][0]["node_config"]["call.from"] = caller
    return detail


async def find(cx: Cx, ref: CallRef) -> Found | Pending | Missing:
    return await PlivoCxRuns(allow_private=True, request_gap_s=0).find(
        source(cx), {"Authorization": "Basic abc"}, ref
    )


async def test_a_run_reads_into_its_lines_saved_values_and_completeness(cx: Cx) -> None:
    cx.add(LIVE_RUN)

    found = await find(cx, call())

    assert isinstance(found, Found)
    record = found.record
    assert (record.external_id, record.status, record.complete) == (
        LIVE_RUN["run_uuid"],
        "COMPLETED",
        True,
    )
    assert [turn.role for turn in record.turns] == [
        Role.AGENT,
        Role.CALLER,
        Role.AGENT,
        Role.CALLER,
        Role.AGENT,
    ]
    assert record.turns[1].text.startswith("Jordan Ellis. Also, quick question.")
    assert record.turns[1].at == datetime(2026, 10, 23, 12, 28, 45, 306851, tzinfo=UTC)
    assert record.turns[1].started_at == datetime(2026, 10, 23, 12, 28, 38, 542427, tzinfo=UTC)
    assert {value.name: value.value for value in record.saved} == {
        "caller_age": "34",
        "caller_full_name": "Jordan Ellis",
    }
    assert cx.auth == ["Basic abc"]


async def test_an_inbound_call_finds_its_run_by_number_among_runs_of_the_same_second(
    cx: Cx,
) -> None:
    started = "2026-10-23 12:28:26.000000+00:00"
    cx.add(run_like_live("run-ours", YAKSH, started, "2026-10-23 12:29:30.000000+00:00"))
    cx.add(run_like_live("run-other", "+15550100009", started, "2026-10-23 12:29:14.000000+00:00"))
    cx.add(run_like_live("run-third", "+15550100008", started, "2026-10-23 12:28:48.000000+00:00"))
    cx.add(
        run_like_live(
            "run-before",
            YAKSH,
            "2026-10-23 12:20:00.000000+00:00",
            "2026-10-23 12:21:00.000000+00:00",
        )
    )

    found = await find(cx, call())

    assert isinstance(found, Found)
    assert found.record.external_id == "run-ours"
    assert cx.read == ["run-other", "run-ours"], "the run that ends closest is read first"


async def test_calls_placed_together_read_each_others_runs_once(cx: Cx) -> None:
    started = "2026-10-23 12:28:26.000000+00:00"
    cx.add(run_like_live("run-ours", YAKSH, started, "2026-10-23 12:29:30.000000+00:00"))
    cx.add(run_like_live("run-other", "+15550100009", started, "2026-10-23 12:29:14.000000+00:00"))
    reader = PlivoCxRuns(allow_private=True, request_gap_s=0)

    async def look(ref: CallRef) -> Found | Pending | Missing:
        return await reader.find(source(cx), {"Authorization": "Basic abc"}, ref)

    ours = await look(call())
    cx.read.clear()
    theirs = await look(replace(call(), yaksh_number="+15550100009"))
    again = await look(call())

    assert isinstance(ours, Found) and isinstance(theirs, Found) and isinstance(again, Found)
    assert theirs.record.external_id == "run-other"
    assert cx.read == ["run-other", "run-ours"], "each lookup reads only its own run again"


async def test_the_requests_of_calls_that_end_together_keep_a_gap(cx: Cx) -> None:
    started = "2026-10-23 12:28:26.000000+00:00"
    callers = [f"+1555010010{n}" for n in range(4)]
    for n, number in enumerate(callers):
        cx.add(run_like_live(f"run-{n}", number, started, f"2026-10-23 12:29:3{n}.000000+00:00"))
    reader = PlivoCxRuns(allow_private=True, request_gap_s=0.2)

    found = await asyncio.gather(
        *(
            reader.find(source(cx), {"Authorization": "Basic abc"}, replace(call(), yaksh_number=n))
            for n in callers
        )
    )

    assert all(isinstance(lookup, Found) for lookup in found)
    gaps = [later - earlier for earlier, later in zip(cx.arrived, cx.arrived[1:], strict=False)]
    assert min(gaps) >= 0.19, "one Auth ID gets one request each gap, from all lookups together"


async def test_a_refusal_for_the_rate_limit_holds_the_next_request(cx: Cx) -> None:
    reader = PlivoCxRuns(allow_private=True, request_gap_s=0)
    cx.status, cx.headers = 429, {"Retry-After": "1"}
    refused = await reader.find(source(cx), {"Authorization": "Basic abc"}, call())
    cx.status, cx.headers = 200, {}

    await reader.find(source(cx), {"Authorization": "Basic abc"}, call())

    assert isinstance(refused, Pending)
    assert cx.arrived[1] - cx.arrived[0] >= 0.95, "Yaksh waits as long as Plivo CX asked"


async def test_a_long_hold_frees_the_evaluation_instead_of_waiting_in_it(cx: Cx) -> None:
    reader = PlivoCxRuns(allow_private=True, request_gap_s=0)
    cx.status, cx.headers = 429, {"Retry-After": "60"}
    await reader.find(source(cx), {"Authorization": "Basic abc"}, call())
    cx.status, cx.headers = 200, {}

    held = await reader.find(source(cx), {"Authorization": "Basic abc"}, call())

    assert isinstance(held, Pending) and held.retry_after_s is not None
    assert 55 <= held.retry_after_s <= 60
    assert len(cx.arrived) == 1, "no request while Plivo CX holds the Auth ID"


async def test_a_hold_applies_to_requests_that_were_already_waiting(cx: Cx) -> None:
    started = "2026-10-23 12:28:26.000000+00:00"
    callers = [f"+1555010010{n}" for n in range(3)]
    for n, number in enumerate(callers):
        cx.add(run_like_live(f"run-{n}", number, started, f"2026-10-23 12:29:3{n}.000000+00:00"))
    reader = PlivoCxRuns(allow_private=True, request_gap_s=0.3)
    ref = replace(call(), yaksh_number=callers[0])
    first = asyncio.create_task(reader.find(source(cx), {"Authorization": "Basic abc"}, ref))
    await asyncio.sleep(0.05)
    reader._pace.hold("MAXXXXXXXXXXXXXXXXXX", 1.0)

    await first

    gaps = [later - earlier for earlier, later in zip(cx.arrived, cx.arrived[1:], strict=False)]
    assert gaps and max(gaps) >= 0.95, "the waiting request goes after the hold, not before"


async def test_runs_of_other_calls_that_were_read_do_not_count_against_the_reads(cx: Cx) -> None:
    started = "2026-10-23 12:28:26.000000+00:00"
    for n in range(MAX_CANDIDATES + 2):
        cx.add(
            run_like_live(
                f"run-{n:02}", f"+1555020{n:04}", started, f"2026-10-23 12:29:{n:02}.000000+00:00"
            )
        )
    cx.add(run_like_live("run-ours", YAKSH, started, "2026-10-23 12:40:00.000000+00:00"))
    reader = PlivoCxRuns(allow_private=True, request_gap_s=0)

    async def look() -> Found | Pending | Missing:
        return await reader.find(source(cx), {"Authorization": "Basic abc"}, call())

    first, second = await look(), await look()

    assert isinstance(first, Pending) and "does not read the other 3" in first.reason
    assert isinstance(second, Found) and second.record.external_id == "run-ours"


async def test_no_run_from_the_number_is_pending_until_one_comes(cx: Cx) -> None:
    cx.add(
        run_like_live(
            "run-other",
            "+15550100009",
            "2026-10-23 12:28:26.000000+00:00",
            "2026-10-23 12:29:14.000000+00:00",
        )
    )

    found = await find(cx, call())

    assert isinstance(found, Pending)
    assert YAKSH in found.reason and found.partial is None


async def test_a_run_still_running_is_pending_with_what_it_has_so_far(cx: Cx) -> None:
    running = copy.deepcopy(LIVE_RUN)
    running["status"] = "IN_PROGRESS"
    running["logs"] = running["logs"][:13]
    cx.add(running)

    found = await find(cx, call())

    assert isinstance(found, Pending)
    assert found.partial is not None and not found.partial.complete
    assert len(found.partial.turns) == 3


async def test_an_outbound_call_reads_the_run_its_trigger_started(cx: Cx) -> None:
    outbound = copy.deepcopy(LIVE_RUN)
    outbound["logs"][0]["node_config"] = {"call.from": "+15550100002", "call.to": YAKSH}
    cx.add(outbound)
    trigger = json.dumps({"api_id": LIVE_RUN["run_uuid"], "message": "Phlo run queued"})

    found = await find(cx, call(Direction.OUTBOUND, trigger))
    other = await find(cx, call(Direction.OUTBOUND, '{"message": "queued"}'))

    assert isinstance(found, Found) and cx.read == [LIVE_RUN["run_uuid"]]
    assert isinstance(other, Missing) and "api_id" in other.reason


async def test_a_run_that_called_another_number_is_not_the_calls(cx: Cx) -> None:
    elsewhere = copy.deepcopy(LIVE_RUN)
    elsewhere["logs"][0]["node_config"] = {"call.from": "+15550100002", "call.to": "+15550100007"}
    cx.add(elsewhere)

    found = await find(cx, call(Direction.OUTBOUND, json.dumps({"api_id": LIVE_RUN["run_uuid"]})))

    assert isinstance(found, Missing) and "+15550100007" in found.reason


@pytest.mark.parametrize(
    ("status", "headers", "expected", "wait"),
    [
        (401, {}, Missing, None),
        (429, {"Retry-After": "7"}, Pending, 7.0),
        (503, {}, Pending, None),
    ],
)
async def test_what_plivo_cx_answers_decides_whether_waiting_helps(
    cx: Cx, status: int, headers: dict[str, str], expected: type, wait: float | None
) -> None:
    cx.status, cx.headers = status, headers

    found = await find(cx, call())

    assert isinstance(found, expected)
    if isinstance(found, Pending):
        assert found.retry_after_s == wait


async def test_two_nodes_that_save_one_name_keep_their_node_in_it(cx: Cx) -> None:
    detail = copy.deepcopy(LIVE_RUN)
    detail["logs"] = [
        *detail["logs"][:-1],
        {"event_name": "NODE_EXECUTED", "node_uuid": "booking", "current_node": "Booking"},
        {
            "event_name": "NODE_CHUNK_CREATED",
            "sender": "assistant",
            "text": "",
            "node_uuid": "booking",
            "node_config": {"variables": {"caller_age": 35, "slot": None, "note": "A\u0000B"}},
        },
        {
            "event_name": "SYSTEM_CHUNK_CREATED",
            "type": "TOOL_CALL_EVENT",
            "tool_name": "book",
            "tool_input": {"slot": "09:30"},
            "tool_response": '{"ok": true}',
            "tool_call_error": False,
            "timestamp": "2026-10-23T12:29:13.900000",
        },
        detail["logs"][-1],
    ]
    cx.add(detail)

    found = await find(cx, call())

    assert isinstance(found, Found)
    saved = {value.name: value.value for value in found.record.saved}
    assert saved == {
        "Dental Front Desk.caller_age": "34",
        "caller_full_name": "Jordan Ellis",
        "Booking.caller_age": "35",
        "slot": "",
        "note": "AB",
    }
    [tool] = found.record.tools
    assert (tool.name, tool.arguments, tool.output, tool.failed) == (
        "book",
        '{"slot": "09:30"}',
        '{"ok": true}',
        False,
    )


async def test_a_line_starts_at_the_last_start_of_its_speaker_before_it(cx: Cx) -> None:
    detail = copy.deepcopy(LIVE_RUN)
    noise = {
        "event_name": "SYSTEM_CHUNK_CREATED",
        "type": "USER_STARTED_SPEAKING",
        "timestamp": "2026-10-23T12:28:36.000000",
    }
    at = next(
        i for i, entry in enumerate(detail["logs"]) if entry.get("text") == "User started speaking"
    )
    detail["logs"].insert(at, noise)
    cx.add(detail)

    found = await find(cx, call())

    assert isinstance(found, Found)
    caller = found.record.turns[1]
    assert caller.started_at == datetime(2026, 10, 23, 12, 28, 38, 542427, tzinfo=UTC), (
        "speech that gave no line does not start the next line"
    )


async def test_a_run_that_just_ended_waits_until_its_log_settles(cx: Cx) -> None:
    fresh = copy.deepcopy(LIVE_RUN)
    fresh["logs"][0]["node_config"] = {"call.from": "+15550100002", "call.to": YAKSH}
    now = datetime.now(UTC)
    fresh["ended_at"] = now.isoformat()
    fresh["logs"][-1]["timestamp"] = now.replace(tzinfo=None).isoformat()
    cx.add(fresh)

    found = await find(cx, call(Direction.OUTBOUND, json.dumps({"api_id": fresh["run_uuid"]})))

    assert isinstance(found, Pending), "Plivo CX logs lines late, after the flow ends"
    assert found.partial is not None and not found.partial.complete
    assert found.retry_after_s is not None and 80 <= found.retry_after_s <= 90, (
        "asked again when the log settles, not at each poll before"
    )


async def test_a_run_that_has_not_logged_its_caller_yet_is_waited_for(cx: Cx) -> None:
    unlogged = run_like_live(
        "run-early",
        YAKSH,
        "2026-10-23 12:28:26.000000+00:00",
        "2026-10-23 12:29:14.000000+00:00",
    )
    unlogged["logs"] = unlogged["logs"][1:]
    cx.add(unlogged)

    found = await find(cx, call())

    assert isinstance(found, Pending) and "run-early" in found.reason


async def test_runs_that_ended_are_read_before_runs_still_going(cx: Cx) -> None:
    started = "2026-10-23 12:28:26.000000+00:00"
    for number in range(MAX_CANDIDATES):
        going = run_like_live(f"run-going-{number}", f"+1555010010{number}", started, started)
        going.update(status="IN_PROGRESS", ended_at=None)
        cx.add(going)
    cx.add(run_like_live("run-ours", YAKSH, started, "2026-10-23 12:29:16.000000+00:00"))

    found = await find(cx, call())

    assert isinstance(found, Found) and found.record.external_id == "run-ours"
    assert cx.read == ["run-ours"]


@pytest.mark.parametrize("odd", ["variables", "started_at", "logs"])
async def test_a_run_in_a_shape_yaksh_does_not_read_is_missing_with_why(cx: Cx, odd: str) -> None:
    detail = copy.deepcopy(LIVE_RUN)
    if odd == "variables":
        detail["logs"][3]["node_config"]["variables"] = ["caller_age", "34"]
    if odd == "logs":
        detail["logs"] = {}
    cx.add(detail)
    if odd == "started_at":
        cx.summaries[0]["started_at"] = "yesterday"

    found = await find(cx, call())

    assert isinstance(found, Missing) and "shape" in found.reason
