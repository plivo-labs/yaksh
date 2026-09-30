import pytest

from truman.domain.conversations import ConversationStatus, EndReason, OutcomeGroup, outcome_group
from truman.domain.runs import RunStatus, run_status

FAILED = {
    None: OutcomeGroup.ERROR,
    EndReason.USER_REQUEST: OutcomeGroup.CANCELLED,
    EndReason.CALLER_HANGUP: OutcomeGroup.ERROR,
    EndReason.AGENT_HANGUP: OutcomeGroup.DID_NOT_CONNECT,
    EndReason.AGENT_SILENT: OutcomeGroup.ERROR,
    EndReason.NO_ANSWER: OutcomeGroup.DID_NOT_CONNECT,
    EndReason.STREAM_ENDED: OutcomeGroup.ERROR,
    EndReason.DURATION_LIMIT: OutcomeGroup.ERROR,
    EndReason.ERROR: OutcomeGroup.ERROR,
    EndReason.WORKER_STOPPED: OutcomeGroup.ERROR,
    EndReason.LEASE_LOST: OutcomeGroup.ERROR,
    EndReason.TRIGGER_FAILED: OutcomeGroup.DID_NOT_CONNECT,
    EndReason.NO_CALL: OutcomeGroup.DID_NOT_CONNECT,
}
"""A failed conversation's group by end reason. Every end reason is listed, so a new one fails
the test below until it is given a group."""
OTHERS = {
    ConversationStatus.QUEUED: OutcomeGroup.WAITING,
    ConversationStatus.RUNNING: OutcomeGroup.IN_PROGRESS,
    ConversationStatus.ENDING: OutcomeGroup.IN_PROGRESS,
    ConversationStatus.COMPLETED: OutcomeGroup.COMPLETED,
    ConversationStatus.INVALID: OutcomeGroup.ERROR,
    ConversationStatus.CANCELLED: OutcomeGroup.CANCELLED,
}


@pytest.mark.parametrize("status", list(ConversationStatus))
@pytest.mark.parametrize("end_reason", [None, *EndReason])
def test_every_status_and_end_reason_is_in_one_group(
    status: ConversationStatus, end_reason: EndReason | None
) -> None:
    if status is ConversationStatus.FAILED:
        expected = FAILED[end_reason]
    elif end_reason is EndReason.USER_REQUEST:
        expected = OutcomeGroup.CANCELLED
    else:
        expected = OTHERS[status]

    assert outcome_group(status, end_reason) is expected


@pytest.mark.parametrize(
    ("cancelled", "active", "started", "status"),
    [
        (False, True, False, RunStatus.QUEUED),
        (False, True, True, RunStatus.RUNNING),
        (False, False, False, RunStatus.DONE),
        (False, False, True, RunStatus.DONE),
        (True, True, False, RunStatus.CANCELLING),
        (True, True, True, RunStatus.CANCELLING),
        (True, False, True, RunStatus.CANCELLED),
    ],
)
def test_a_run_status_comes_from_its_conversations(
    cancelled: bool, active: bool, started: bool, status: RunStatus
) -> None:
    assert run_status(cancelled=cancelled, active=active, started=started) is status
