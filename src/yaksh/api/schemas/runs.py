import uuid
from datetime import datetime

from yaksh.db.models import Run
from yaksh.domain.languages import Language
from yaksh.domain.latency import Latency
from yaksh.domain.runs import RunProgress, RunScenario


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
    response_p50_ms: int | None
    response_p90_ms: int | None
    """Nearest rank over every measured reply of the latest attempts, pooled."""
    languages: list[Language]
    """The languages the run's callers speak."""

    @classmethod
    def of(
        cls,
        run: Run,
        agent: tuple[int, str],
        progress: RunProgress,
        response: Latency,
        languages: list[Language],
    ) -> RunSummary:
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
            response_p50_ms=response.p50_ms,
            response_p90_ms=response.p90_ms,
            languages=languages,
            **progress.model_dump(),
        )


class RunRead(RunSummary):
    scenarios: list[RunScenario]
    """With the personas that call them, in the order the conversations of each repeat
    start."""
