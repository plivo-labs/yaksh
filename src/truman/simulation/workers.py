from datetime import timedelta

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from truman.db.models import RunningWorker


def seen_within(lease_s: int) -> ColumnElement[bool]:
    return RunningWorker.seen_at > func.now() - timedelta(seconds=lease_s)


async def report_worker(
    session: AsyncSession,
    worker_id: str,
    *,
    receiving_app_id: str | None,
    outbound_problem: str | None,
    lease_s: int,
) -> None:
    """Record the worker as running, and forget workers not seen for a lease."""
    await session.execute(delete(RunningWorker).where(~seen_within(lease_s)))
    row = {
        "receiving_app_id": receiving_app_id,
        "outbound_problem": outbound_problem,
        "seen_at": func.now(),
    }
    await session.execute(
        insert(RunningWorker)
        .values(id=worker_id, **row)
        .on_conflict_do_update(index_elements=[RunningWorker.id], set_=row)
    )
    await session.commit()


async def receiving_problem(session: AsyncSession, app_id: str, lease_s: int) -> str | None:
    """Why no running worker receives calls for the Plivo application, or None when one does."""
    receiving = await session.scalar(
        select(RunningWorker.id)
        .where(seen_within(lease_s), RunningWorker.receiving_app_id == app_id)
        .limit(1)
    )
    if receiving is not None:
        return None
    problems = await session.scalars(
        select(RunningWorker.outbound_problem)
        .where(seen_within(lease_s), RunningWorker.outbound_problem.is_not(None))
        .distinct()
        .order_by(RunningWorker.outbound_problem)
    )
    return (
        "; ".join(filter(None, problems))
        or f"no running worker receives calls for application {app_id}"
    )
