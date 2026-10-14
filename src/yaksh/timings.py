"""How often the workers poll and report, and how long their leases last. They are fixed in
code, not settings: the API and every worker must agree on the lease, and the heartbeat must
stay well under it. Tests pass faster ones."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Timings:
    worker_poll_s: float = 0.5
    worker_heartbeat_s: float = 1.0
    worker_lease_s: float = 30
    """A worker not seen for this long has stopped, and its conversations are reaped."""
    evaluator_poll_s: float = 2.0
    evaluator_lease_s: float = 60
    end_timeout_s: float = 5.0
    """How long a stopping call, server or database pool gets to end on its own."""


TIMINGS = Timings()
