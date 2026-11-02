"""The trace token, the spans that the OTLP endpoint keeps, and their cleanup."""

import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from yaksh.db.models import AgentSpan, AgentTraceOwner, PhoneNumber, TraceToken
from yaksh.domain.traces import KeptSpan, new_token, token_sha256

TOKEN_ROW = 1
TOUCH_EVERY = timedelta(seconds=30)
"""How often a busy exporter may write the token's times."""
KEEP = timedelta(days=7)
"""How long spans and links stay, linked or not."""
NUMBERS_TTL_S = 60.0


async def current_token(session: AsyncSession) -> TraceToken | None:
    return await session.get(TraceToken, TOKEN_ROW)


async def token_with(session: AsyncSession, token: str) -> TraceToken | None:
    return await session.scalar(
        select(TraceToken).where(TraceToken.token_sha256 == token_sha256(token))
    )


async def make_token(session: AsyncSession) -> tuple[TraceToken, str]:
    """A new token in place of the one there was, which stops at once. Only its hash is kept,
    so this is the one time anyone sees it."""
    token = new_token()
    values = {"token_sha256": token_sha256(token), "hint": token[-4:]}
    row = await session.scalar(
        insert(TraceToken)
        .values(id=TOKEN_ROW, **values)
        .on_conflict_do_update(
            index_elements=[TraceToken.id],
            set_=values | {"created_at": func.now(), "last_used_at": None, "last_key_at": None},
        )
        .returning(TraceToken)
    )
    await session.commit()
    assert row is not None
    return row, token


async def delete_token(session: AsyncSession) -> None:
    await session.execute(delete(TraceToken))
    await session.commit()


async def store_spans(session: AsyncSession, token: TraceToken, spans: Sequence[KeptSpan]) -> None:
    """Keep the spans, one copy of each, and note on the token that it was used, and whether a
    kept span had a link key. A request with a replaced token changes no times: its hash is not
    the row's any more. The rows go as a list of parameters, which SQLAlchemy sends in pages:
    one INSERT with all of them goes past asyncpg's 32,767 parameters at 3,641 spans."""
    if spans:
        await session.execute(
            insert(AgentSpan).on_conflict_do_nothing(
                index_elements=[AgentSpan.trace_id, AgentSpan.span_id]
            ),
            [
                {
                    key: value
                    for key, value in asdict(span).items()
                    if key not in ("conversation_id", "number")
                }
                | {"link_conversation_id": span.conversation_id, "link_number": span.number}
                for span in spans
            ],
        )
    await touch(session, token, TraceToken.last_used_at)
    if any(span.keyed for span in spans):
        await touch(session, token, TraceToken.last_key_at)
    await session.commit()


async def touch(
    session: AsyncSession, token: TraceToken, column: InstrumentedAttribute[datetime | None]
) -> None:
    await session.execute(
        update(TraceToken)
        .where(
            TraceToken.token_sha256 == token.token_sha256,
            or_(column.is_(None), column < func.now() - TOUCH_EVERY),
        )
        .values({column: func.now()})
    )


class YakshNumbers:
    """Yaksh's numbers, read again at most once a minute: the endpoint reads them on every
    request."""

    def __init__(self) -> None:
        self._numbers: frozenset[str] = frozenset()
        self._read_at = -NUMBERS_TTL_S

    async def get(self, session: AsyncSession) -> frozenset[str]:
        if time.monotonic() - self._read_at >= NUMBERS_TTL_S:
            self._numbers = frozenset(await session.scalars(select(PhoneNumber.number)))
            self._read_at = time.monotonic()
        return self._numbers


async def clean(session: AsyncSession, now: datetime) -> tuple[int, int]:
    """Delete the spans and the links older than KEEP; return how many of each."""
    spans = cast(
        CursorResult[Any],
        await session.execute(delete(AgentSpan).where(AgentSpan.received_at < now - KEEP)),
    )
    owners = cast(
        CursorResult[Any],
        await session.execute(
            delete(AgentTraceOwner).where(AgentTraceOwner.linked_at < now - KEEP)
        ),
    )
    await session.commit()
    return spans.rowcount, owners.rowcount
