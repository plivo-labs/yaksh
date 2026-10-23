import asyncio
import time
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

import numpy as np
import onnxruntime
import pytest
from pipecat.audio.turn.base_turn_analyzer import BaseTurnAnalyzer
from pipecat.audio.turn.smart_turn import base_smart_turn
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADState
from pipecat.metrics.metrics import TurnMetricsData

from yaksh.caller.audio import SAMPLE_RATE
from yaksh.caller.pipeline import VAD
from yaksh.caller.turn_models import TurnModels

FRAME_S = 0.02
FRAME_BYTES = int(SAMPLE_RATE * FRAME_S) * 2
AUDIO_TIME: ContextVar[float] = ContextVar("audio_time")
VOWELS = ((700, 1220, 2600), (300, 2300, 3000), (450, 900, 2400), (400, 1900, 2550))


def syllable(rng: np.random.Generator) -> np.ndarray:
    seconds = rng.uniform(0.12, 0.25)
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    pitch = rng.uniform(110, 140)
    formants = VOWELS[rng.integers(len(VOWELS))]
    wave = np.zeros_like(t)
    for harmonic in range(1, int(3800 / pitch)):
        gain = sum(1 / (1 + ((harmonic * pitch - f) / 120) ** 2) for f in formants)
        wave += gain / harmonic**0.5 * np.sin(2 * np.pi * harmonic * pitch * t)
    return wave / np.abs(wave).max() * np.sin(np.pi * t / seconds) ** 0.6


def speech(seed: int) -> list[bytes]:
    """20 ms frames of three utterances of vowel sounds, which Silero hears as speech, each
    followed by a pause long enough for a model reset."""
    rng = np.random.default_rng(seed)
    pause = np.zeros(int(SAMPLE_RATE * 2.5))
    parts = [pause]
    for _ in range(3):
        parts += [syllable(rng) for _ in range(rng.integers(6, 12))]
        parts.append(pause)
    pcm = (np.concatenate(parts) * 16000).astype(np.int16).tobytes()
    return [pcm[at : at + FRAME_BYTES] for at in range(0, len(pcm), FRAME_BYTES)]


@pytest.fixture
def audio_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smart Turn picks the audio before speech by the time each frame arrived. Here each stream
    gives its own audio time instead, so that a slow machine sends the model the same audio."""
    clock = SimpleNamespace(monotonic=AUDIO_TIME.get, perf_counter=time.perf_counter)
    monkeypatch.setattr(base_smart_turn, "time", clock)


async def hear(
    vad: VADAnalyzer, turn: BaseTurnAnalyzer, frames: list[bytes]
) -> tuple[list[VADState], list[float]]:
    """The VAD state after each frame, and the end-of-turn probability at each stop of speech."""
    vad.set_sample_rate(SAMPLE_RATE)
    turn.set_sample_rate(SAMPLE_RATE)
    states: list[VADState] = []
    ends: list[float] = []
    speaking = False
    for index, frame in enumerate(frames):
        AUDIO_TIME.set(index * FRAME_S)
        state = await vad.analyze_audio(frame)
        turn.append_audio(frame, is_speech=state is VADState.SPEAKING)
        if speaking and state is VADState.QUIET:
            _, metrics = await turn.analyze_end_of_turn()
            assert isinstance(metrics, TurnMetricsData)
            ends.append(metrics.probability)
        speaking = state in (VADState.SPEAKING, VADState.STOPPING)
        states.append(state)
    await vad.cleanup()
    await turn.cleanup()
    return states, ends


@pytest.mark.usefixtures("audio_clock")
async def test_calls_that_share_the_sessions_hear_what_pipecats_own_analyzers_hear() -> None:
    tracks = [speech(seed) for seed in (1, 2)]
    expected = [
        await hear(SileroVADAnalyzer(params=VAD), LocalSmartTurnAnalyzerV3(), frames)
        for frames in tracks
    ]
    models = TurnModels()

    heard = await asyncio.gather(
        *(
            hear(models.vad(sample_rate=SAMPLE_RATE, params=VAD), models.end_of_turn(), frames)
            for frames in tracks
        )
    )

    assert [len(ends) for _, ends in expected] == [3, 3]
    assert heard == expected


def test_a_calls_analyzers_load_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    models = TurnModels()
    loads: list[Any] = []
    monkeypatch.setattr(onnxruntime, "InferenceSession", lambda *args, **_: loads.append(args))

    models.vad(sample_rate=SAMPLE_RATE, params=VAD)
    models.end_of_turn()

    assert loads == []
