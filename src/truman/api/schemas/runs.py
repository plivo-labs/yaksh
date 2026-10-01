import uuid
from datetime import datetime

from truman.db.models import Run
from truman.domain.runs import RunProgress


class RunSummary(RunProgress):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    agent_version: int
    agent_name: str
    name: str | None
    repeats: int
    max_duration_s: int
    max_turns: int
    max_parallel: int | None
    start_interval_s: int | None
    max_retries: int
    created_at: datetime

    @classmethod
    def of(cls, run: Run, agent: tuple[int, str], progress: RunProgress) -> RunSummary:
        """The run's own columns and its pinned agent; status and cancelled_at come only from
        the progress, read in one statement."""
        agent_version, agent_name = agent
        return cls(
            id=run.id,
            agent_id=run.agent_id,
            agent_version_id=run.agent_version_id,
            agent_version=agent_version,
            agent_name=agent_name,
            name=run.name,
            repeats=run.repeats,
            max_duration_s=run.max_duration_s,
            max_turns=run.max_turns,
            max_parallel=run.max_parallel,
            start_interval_s=run.start_interval_s,
            max_retries=run.max_retries,
            created_at=run.created_at,
            **progress.model_dump(),
        )


class RunRead(RunSummary):
    scenario_ids: list[uuid.UUID]
    """In the order the conversations of each repeat start."""
