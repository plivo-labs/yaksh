from enum import StrEnum


class Channel(StrEnum):
    VOICE = "voice"


class ConversationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    ENDING = "ending"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALID = "invalid"
    CANCELLED = "cancelled"


class EndReason(StrEnum):
    USER_REQUEST = "user_request"
    GOAL_REACHED = "goal_reached"
    AGENT_HANGUP = "agent_hangup"
    DURATION_LIMIT = "duration_limit"
    ERROR = "error"
    PROCESS_RESTART = "process_restart"


ACTIVE_STATUSES = frozenset(
    {ConversationStatus.QUEUED, ConversationStatus.RUNNING, ConversationStatus.ENDING}
)
