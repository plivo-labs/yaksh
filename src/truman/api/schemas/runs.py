import uuid
from datetime import datetime

from truman.db.models import Run
from truman.domain.background_noise import BackgroundNoise
from truman.domain.latency import Latency
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
    background_noise: BackgroundNoise | None
    """None: each conversation plays its persona's own setting."""
    created_at: datetime
    response_p50_ms: int | None
    response_p90_ms: int | None
    """Nearest rank over every measured reply of the latest attempts, pooled."""

    @classmethod
    def of(
        cls, run: Run, agent: tuple[int, str], progress: RunProgress, response: Latency
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
            background_noise=(
                None
                if run.background_noise_sound is None or run.background_noise_level is None
                else BackgroundNoise(
                    sound=run.background_noise_sound, level=run.background_noise_level
                )
            ),
            created_at=run.created_at,
            response_p50_ms=response.p50_ms,
            response_p90_ms=response.p90_ms,
            **progress.model_dump(),
        )


class RunRead(RunSummary):
    scenario_ids: list[uuid.UUID]
    """In the order the conversations of each repeat start."""
