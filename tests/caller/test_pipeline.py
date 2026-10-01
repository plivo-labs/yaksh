from pathlib import Path

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    LLMContextFrame,
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
from truman.caller.pipeline import CallState, TurnLimit, llm_service, watch_silence
from truman.config import Settings
from truman.domain.conversations import EndReason

KEYS = ("deepgram_api_key", "elevenlabs_api_key", "openai_api_key")


def model_settings(tmp_path: Path, base: str, model: str, effort: str | None) -> Settings:
    return make_settings(
        tmp_path,
        **dict.fromkeys(KEYS, "test"),
        openai_base_url=f"{base}/v1",
        persona_llm_model=model,
        persona_llm_reasoning_effort=effort,
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
    ("model", "effort", "reasoning"),
    [
        ("gpt-6-luna", None, {"effort": "none"}),
        ("gpt-4.1", None, None),
        ("gpt-6-luna", "low", {"effort": "low"}),
    ],
    ids=["reasoning model", "gpt-4.x", "configured effort"],
)
async def test_the_persona_asks_the_responses_api_with_reasoning_off_unless_configured(
    provider: tuple[str, FakeProvider],
    tmp_path: Path,
    model: str,
    effort: str | None,
    reasoning: dict | None,
) -> None:
    base, fake = provider
    settings = model_settings(tmp_path, base, model, effort)
    llm = llm_service(settings, {"OPENAI_API_KEY": "test"}, "Be a caller.")

    await llm.run_inference(LLMContext(messages=[{"role": "user", "content": "Hello."}]))

    path, _, body = fake.requests[0]
    assert (path, body["model"], body.get("reasoning")) == ("/v1/responses", model, reasoning)


async def test_the_persona_answers_its_most_agent_turns_and_then_the_limit_takes_over() -> None:
    reached: list[str] = []

    async def at_limit() -> None:
        reached.append("goodbye")

    def after(*agent_turns: str) -> LLMContext:
        return LLMContext(messages=[{"role": "user", "content": turn} for turn in agent_turns])

    opening = LLMContextFrame(context=after())
    turns = [
        opening,
        LLMContextFrame(context=after("Hi.")),
        LLMContextFrame(context=after("Hi.", "Your name?"), speculation=True),
        LLMContextFrame(context=after("Hi.", "Your name?")),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?"), speculation=True),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?")),
        LLMContextFrame(context=after("Hi.", "Your name?", "Age?", "Hello?")),
    ]

    down, _ = await run_test(TurnLimit(2, at_limit), frames_to_send=turns)

    asked = [frame for frame in down if isinstance(frame, LLMContextFrame)]
    assert asked[0] is opening
    assert [frame.speculation for frame in asked] == [False, False, True, False]
    assert reached == ["goodbye"]
