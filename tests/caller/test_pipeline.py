from pathlib import Path

import pytest
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

from tests.conftest import FakeProvider, make_settings
from truman.caller import pipeline
from truman.caller.pipeline import CallState, llm_service, persona_turn_options, watch_silence
from truman.config import Settings
from truman.domain.conversations import EndReason

KEYS = ("deepgram_api_key", "elevenlabs_api_key", "openai_api_key")


def model_settings(tmp_path: Path, base: str) -> Settings:
    return make_settings(
        tmp_path,
        **dict.fromkeys(KEYS, "test"),
        openai_base_url=f"{base}/v1",
        persona_llm_model="gpt-6-luna",
    )


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


@pytest.mark.parametrize(
    ("reasoning", "outages", "options", "checks"),
    [
        (True, 0, {"reasoning_effort": "none"}, 1),
        (False, 0, {}, 1),
        (True, 2, {"reasoning_effort": "none"}, 3),
        (True, 3, {}, 3),
    ],
)
async def test_the_worker_sends_the_persona_effort_only_once_a_check_says_the_model_takes_it(
    provider: tuple[str, FakeProvider],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reasoning: bool,
    outages: int,
    options: dict[str, str],
    checks: int,
) -> None:
    base, fake = provider
    fake.reasoning = reasoning
    fake.outages = outages
    monkeypatch.setattr(pipeline, "CHECK_PAUSE_S", 0)

    assert await persona_turn_options(model_settings(tmp_path, base)) == options
    assert fake.efforts() == ["none"] * checks


@pytest.mark.parametrize("options", [{"reasoning_effort": "none"}, {}])
async def test_each_persona_turn_sends_the_turn_options(
    provider: tuple[str, FakeProvider], tmp_path: Path, options: dict[str, str]
) -> None:
    base, fake = provider
    llm = llm_service(
        model_settings(tmp_path, base), {"OPENAI_API_KEY": "test"}, "Be a caller.", options
    )

    await llm.run_inference(LLMContext(messages=[{"role": "user", "content": "Hello."}]))

    assert fake.efforts() == [options.get("reasoning_effort")]
