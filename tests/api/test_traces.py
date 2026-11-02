import asyncio
import gzip
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import timedelta

import pytest
from httpx import AsyncClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span
from sqlalchemy import func, select, text, update

from tests.conftest import Db, claim, evaluate_queued, finish, new_run
from yaksh.api.routes import otlp
from yaksh.db.models import AgentSpan, TraceToken
from yaksh.domain.conversations import CallOutcome, EndReason, Provenance, Role, Transcript, Turn
from yaksh.domain.evaluations import Metric, MetricKey
from yaksh.domain.latency import AgentReplyTime, Latency, Reply

ROUTE = "/api/v1/otlp/v1/traces"
YAKSH_NUMBER = "+15550100001"
"""One of the test pool's numbers."""
START_NS = 1_793_350_000_000_000_000


def value(raw: object) -> AnyValue:
    match raw:
        case bool():
            return AnyValue(bool_value=raw)
        case int():
            return AnyValue(int_value=raw)
        case float():
            return AnyValue(double_value=raw)
        case _:
            return AnyValue(string_value=str(raw))


def span(
    name: str,
    attributes: Mapping[str, object] | None = None,
    *,
    trace: int = 1,
    span_id: int = 1,
    parent: int | None = None,
    start_ns: int = START_NS,
    end_ns: int = START_NS + 1_000_000_000,
) -> Span:
    return Span(
        name=name,
        trace_id=trace.to_bytes(16, "big"),
        span_id=span_id.to_bytes(8, "big"),
        parent_span_id=parent.to_bytes(8, "big") if parent else b"",
        start_time_unix_nano=start_ns,
        end_time_unix_nano=end_ns,
        attributes=[KeyValue(key=key, value=value(raw)) for key, raw in (attributes or {}).items()],
    )


def export(*spans: Span) -> bytes:
    request = ExportTraceServiceRequest()
    request.resource_spans.add().scope_spans.add().spans.extend(spans)
    return request.SerializeToString()


async def make_token(client: AsyncClient) -> str:
    response = await client.post("/api/v1/settings/trace-token")
    assert response.status_code == 201
    return response.json()["token"]


async def send(
    client: AsyncClient, token: str, body: bytes, **headers: str
) -> tuple[int, ExportTraceServiceResponse | None]:
    response = await client.post(
        ROUTE,
        content=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-protobuf",
            **headers,
        },
    )
    if response.status_code != 200:
        return response.status_code, None
    return 200, ExportTraceServiceResponse.FromString(response.content)


async def stored(db: Db) -> list[AgentSpan]:
    async with db() as session:
        return list(await session.scalars(select(AgentSpan).order_by(AgentSpan.span_id)))


async def token_row(db: Db) -> TraceToken:
    async with db() as session:
        row = await session.scalar(select(TraceToken))
    assert row is not None
    return row


async def test_a_call_trace_keeps_names_times_timing_values_and_keys_only(
    client: AsyncClient, db: Db
) -> None:
    token = await make_token(client)
    body = export(
        span(
            "user_turn",
            {
                "lk.pii.user_transcript": "my card ends in 4242",
                "lk.end_of_turn_delay": 0.7,
                "lk.transcription_delay": 0.35,
                "yaksh.number": "15550100001",
            },
            span_id=1,
        ),
        span("agent_turn", {"lk.speech_id": "s7", "lk.e2e_latency": 2}, span_id=2, parent=1),
        span("a_span_of_the_agent", {"yaksh.number": YAKSH_NUMBER}, span_id=3),
        span("a_span_no_reader_uses", {"anything": 1}, span_id=4),
        span("eou_wait", {"lk.eou.source": "vad"}, span_id=6, parent=1),
        span(
            "eou_detection",
            {"lk.chat_ctx": "my card ends in 4242", "lk.eou.source": "vad"},
            span_id=5,
            parent=6,
        ),
    )
    status, answer = await send(client, token, body)

    assert status == 200 and answer is not None and not answer.HasField("partial_success")
    kept = {row.name: row for row in await stored(db)}
    assert set(kept) == {
        "user_turn",
        "agent_turn",
        "a_span_of_the_agent",
        "eou_wait",
        "eou_detection",
    }
    assert kept["eou_detection"].attributes == {"lk.eou.source": "vad"}
    assert kept["user_turn"].attributes == {
        "lk.end_of_turn_delay": 0.7,
        "lk.transcription_delay": 0.35,
    }
    assert kept["user_turn"].link_number == YAKSH_NUMBER
    assert kept["agent_turn"].attributes == {"lk.speech_id": "s7", "lk.e2e_latency": 2.0}
    assert kept["agent_turn"].parent_span_id == (1).to_bytes(8, "big").hex()
    assert kept["a_span_of_the_agent"].attributes == {}
    assert kept["a_span_of_the_agent"].link_number == YAKSH_NUMBER


async def test_gzip_and_plain_bodies_store_the_same_spans_and_a_retry_adds_none(
    client: AsyncClient, db: Db
) -> None:
    token = await make_token(client)
    body = export(
        span("llm_node", {"lk.response.ttft": 0.6}, span_id=1), span("tts_node", span_id=2)
    )

    assert (await send(client, token, gzip.compress(body), **{"Content-Encoding": "gzip"}))[
        0
    ] == 200
    first = [(row.trace_id, row.span_id, row.attributes) for row in await stored(db)]
    assert (await send(client, token, body))[0] == 200

    assert [(row.trace_id, row.span_id, row.attributes) for row in await stored(db)] == first
    assert len(first) == 2


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (
            span("llm_node", {"lk.response.ttft": "fast"}, span_id=1),
            "lk.response.ttft must be a number from -86400 to 86400",
        ),
        (
            span("llm_node", {"lk.response.ttft": 1e308}, span_id=1),
            "lk.response.ttft must be a number from -86400 to 86400",
        ),
        (span("llm_node", span_id=1, end_ns=2**64 - 1), "a span has a bad start or end time"),
        (
            span("llm_node", {"lk.generation_id": "gen\x00bad"}, span_id=1),
            "lk.generation_id must be a string with no NUL character",
        ),
    ],
)
async def test_a_span_with_a_bad_value_is_rejected_alone(
    client: AsyncClient, db: Db, bad: Span, reason: str
) -> None:
    token = await make_token(client)
    status, answer = await send(
        client, token, export(bad, span("tts_node", {"lk.response.ttfb": 0.18}, span_id=2))
    )

    assert status == 200 and answer is not None
    assert answer.partial_success.rejected_spans == 1
    assert reason in answer.partial_success.error_message
    assert [row.name for row in await stored(db)] == ["tts_node"]


async def test_an_export_of_4000_spans_is_stored_whole(client: AsyncClient, db: Db) -> None:
    """One INSERT of all of them passes the driver's limit of 32,767 parameters."""
    token = await make_token(client)
    body = export(
        *(span("llm_node", {"lk.response.ttft": 0.6}, span_id=index) for index in range(1, 4001))
    )
    status, answer = await send(client, token, body)

    assert status == 200 and answer is not None and not answer.HasField("partial_success")
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(AgentSpan)) == 4000


async def test_a_slow_upload_holds_no_database_connection_and_times_out(
    client: AsyncClient, db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(otlp, "READ_BODY_S", 0.5)
    token = await make_token(client)
    body = export(span("tts_node", {"lk.response.ttfb": 0.18}))
    reading = asyncio.Event()

    async def slowly() -> AsyncIterator[bytes]:
        yield body[:4]
        reading.set()
        await asyncio.Event().wait()
        yield body[4:]

    upload = asyncio.create_task(
        client.post(
            ROUTE,
            content=slowly(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-protobuf"},
        )
    )
    await reading.wait()
    async with db() as session:
        in_transaction = await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND state = 'idle in transaction'"
            )
        )
    response = await asyncio.wait_for(upload, 5)

    assert in_transaction == 0
    assert response.status_code == 408


async def test_a_span_with_another_number_is_dropped_unless_it_names_a_conversation(
    client: AsyncClient, db: Db
) -> None:
    token = await make_token(client)
    conversation = uuid.uuid4()
    body = export(
        span("user_turn", {"yaksh.number": "+14155550199"}, span_id=1),
        span(
            "agent_turn",
            {"yaksh.number": "+14155550199", "yaksh.conversation_id": str(conversation)},
            span_id=2,
        ),
    )
    assert (await send(client, token, body))[0] == 200

    [row] = await stored(db)
    assert (row.name, row.link_conversation_id, row.link_number) == (
        "agent_turn",
        conversation,
        None,
    )


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Content-Type": "application/json"}, 415),
        ({"Content-Encoding": "br"}, 415),
    ],
)
async def test_other_formats_get_415(
    client: AsyncClient, headers: dict[str, str], status: int
) -> None:
    token = await make_token(client)
    assert (await send(client, token, export(span("tts_node")), **headers))[0] == status


async def test_only_the_trace_token_opens_the_route_and_only_this_route(
    client: AsyncClient,
) -> None:
    body = export(span("tts_node"))
    assert (await send(client, "no-token-yet", body))[0] == 401
    token = await make_token(client)
    api_token = client.headers["Authorization"].removeprefix("Bearer ")

    assert (await send(client, api_token, body))[0] == 401
    other = await client.get(
        "/api/v1/settings/trace-token", headers={"Authorization": f"Bearer {token}"}
    )
    assert other.status_code == 401
    assert (await send(client, token, body))[0] == 200


async def test_a_wrong_token_gets_401_before_the_body_is_read(client: AsyncClient) -> None:
    await make_token(client)
    status, _ = await send(client, "wrong", b"\0" * (9 * 1024 * 1024))
    assert status == 401


async def test_large_requests_get_413(client: AsyncClient) -> None:
    token = await make_token(client)
    too_many = export(*(span("tts_node", span_id=n) for n in range(1, 20_002)))
    unzips_large = gzip.compress(b"\0" * (33 * 1024 * 1024))

    assert (await send(client, token, b"\0" * (8 * 1024 * 1024 + 1)))[0] == 413
    assert (await send(client, token, unzips_large, **{"Content-Encoding": "gzip"}))[0] == 413
    assert (await send(client, token, too_many))[0] == 413


async def test_the_token_is_shown_once_and_a_new_one_stops_the_old(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/settings/trace-token")).json() is None
    old = await make_token(client)
    read = (await client.get("/api/v1/settings/trace-token")).json()
    assert old.startswith("yks_") and len(old) == 44
    assert read["hint"] == old[-4:] and "token" not in read

    new = await make_token(client)
    assert (await send(client, old, export(span("tts_node"))))[0] == 401
    assert (await send(client, new, export(span("tts_node"))))[0] == 200
    assert (await client.delete("/api/v1/settings/trace-token")).status_code == 204
    assert (await send(client, new, export(span("tts_node"))))[0] == 401


async def test_the_token_times_show_use_and_kept_keys_at_most_every_30_s(
    client: AsyncClient, db: Db
) -> None:
    token = await make_token(client)
    assert (await send(client, token, export(span("tts_node", span_id=1))))[0] == 200
    used = await token_row(db)
    assert used.last_used_at is not None and used.last_key_at is None

    unkept_key = export(span("tts_node", {"yaksh.number": "+14155550199"}, span_id=2))
    assert (await send(client, token, unkept_key))[0] == 200
    assert (await token_row(db)).last_key_at is None

    keyed = export(span("tts_node", {"yaksh.number": YAKSH_NUMBER}, span_id=3))
    assert (await send(client, token, keyed))[0] == 200
    after = await token_row(db)
    assert after.last_used_at == used.last_used_at
    assert after.last_key_at is not None

    async with db() as session:
        await session.execute(
            update(TraceToken).values(last_used_at=TraceToken.last_used_at - timedelta(seconds=31))
        )
        await session.commit()
    assert (await send(client, token, export(span("tts_node", span_id=4))))[0] == 200
    later = (await token_row(db)).last_used_at
    assert later is not None and after.last_used_at is not None
    assert later > after.last_used_at


async def test_a_new_token_starts_with_empty_times_that_the_old_cannot_change(
    client: AsyncClient, db: Db
) -> None:
    old = await make_token(client)
    keyed = export(span("tts_node", {"yaksh.number": YAKSH_NUMBER}))
    assert (await send(client, old, keyed))[0] == 200
    await make_token(client)

    assert (await send(client, old, keyed))[0] == 401
    row = await token_row(db)
    assert (row.last_used_at, row.last_key_at) == (None, None)


async def test_an_agent_turn_gets_the_traced_parts_of_the_reply_it_starts(
    client: AsyncClient, db: Db
) -> None:
    await new_run(client)
    conversation = await claim(db)
    assert conversation is not None
    transcript = Transcript(
        turns=[
            Turn(role=Role.AGENT, text="Hello?", started_at_ms=0, ended_at_ms=900),
            Turn(
                role=Role.CALLER,
                text="Yes.",
                started_at_ms=1_000,
                ended_at_ms=1_500,
                provenance=Provenance.TRANSMITTED,
                audio_index=0,
            ),
            # The live pipeline got to the turn 400 ms after the speech started.
            Turn(role=Role.AGENT, text="Great.", started_at_ms=3_900, ended_at_ms=4_500),
        ]
    )
    done = CallOutcome(connected=True, end_reason=EndReason.AGENT_HANGUP)
    await finish(db, conversation, done, transcript=transcript)
    reply = AgentReplyTime(
        speech_ms=3_500,
        agent_ms=1_600,
        complete=True,
        fits=True,
        overlapping=False,
        stt_ttfs_ms=300,
        reason=None,
        steps={"network": 400, "llm_inference": 1_600},
    )
    latency = Latency.of([Reply(start_ms=1_500, speech_ms=3_500)])
    await evaluate_queued(
        db,
        {
            conversation: {
                MetricKey.RESPONSE_TIME: Metric(value=latency.model_dump(mode="json")),
                MetricKey.AGENT_REPLY_TIME: Metric(
                    value={"status": "ok", "by_reply": [reply.model_dump(mode="json")]}
                ),
            }
        },
    )

    detail = (await client.get(f"/api/v1/conversations/{conversation}")).json()

    assert [turn["agent_reply"] for turn in detail["transcript"]] == [
        None,
        None,
        reply.model_dump(mode="json"),
    ]
