from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from truman.caller.persona import CallState, watch_silence
from truman.domain.conversations import EndReason


async def test_the_persona_gives_up_on_a_quiet_agent_only_after_two_nudges_in_one_silence() -> None:
    user = LLMContextAggregatorPair(
        LLMContext(),
        user_params=LLMUserAggregatorParams(
            user_idle_timeout=0.05,
            user_turn_strategies=UserTurnStrategies(
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.05)]
            ),
        ),
    ).user()
    state = CallState()
    nudges: list[EndReason | None] = []

    async def nudge() -> None:
        nudges.append(state.end_reason)

    watch_silence(user, state, nudge)
    quiet = [BotStoppedSpeakingFrame(), SleepFrame(0.15)]
    agent_turn = [
        VADUserStartedSpeakingFrame(),
        TranscriptionFrame("Hello.", "agent", "now"),
        VADUserStoppedSpeakingFrame(),
        SleepFrame(0.3),
    ]

    await run_test(user, frames_to_send=[*quiet, *quiet, *agent_turn, *quiet, *quiet, *quiet])

    assert nudges == [None, None, None, None]
    assert state.end_reason is EndReason.AGENT_SILENT
