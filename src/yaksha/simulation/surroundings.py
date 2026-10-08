"""The sound files behind the caller, and the plan that says when each one plays in a call."""

import random
import re
import wave
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from yaksha.domain.languages import Language
from yaksha.domain.surroundings import (
    AutoNoise,
    Layer,
    NoiseSound,
    SoundPlan,
    Speaker,
    SpeakerKind,
    Surroundings,
)

SOUNDS = Path(__file__).parent / "sounds"
"""Read as files: the mixer opens a sound by its path."""
SAMPLE_RATE = 8000
SPEECH_DBFS = -20.0
"""The active speech level of the built-in voices at their persona settings on a call
(eleven_flash_v2_5, pcm_8000), measured at -20.5 to -19.2 dBFS on 2026-10-01. The speaker
clips are made at this level."""
NOISE_DBFS = -25.0
"""The RMS level of every noise loop."""
AUTO_EVENT_S = (3.0, 8.0)
AUTO_GAP_S = (5.0, 20.0)
AUTO_SPREAD_DB = 3
SPEAKER_GAP_S = {
    SpeakerKind.TALKS_TO_CALLER: (4.0, 10.0),
    SpeakerKind.OWN_PHONE_CALL: (3.0, 8.0),
    SpeakerKind.TV: (0.5, 1.5),
}
"""The silence between two clips of a speaker: a TV hardly stops."""
CLIP_LANGUAGE = {Language.EN: "en", Language.HINGLISH: "hi"}
TAG = re.compile(r"\[[^]]*\]\s*")


@dataclass(frozen=True)
class SpeakerLine:
    start_s: float
    text: str


@dataclass(frozen=True)
class SpeakerClip:
    id: str
    language: str
    kind: SpeakerKind
    seconds: float
    lines: tuple[SpeakerLine, ...]

    @property
    def file(self) -> str:
        return f"speakers/{self.id}.wav"


@cache
def speaker_clips() -> tuple[SpeakerClip, ...]:
    listed = yaml.safe_load((SOUNDS / "speakers.yaml").read_text())
    return tuple(
        SpeakerClip(
            id=clip["id"],
            language=clip["language"],
            kind=SpeakerKind(clip["kind"]),
            seconds=clip["seconds"],
            lines=tuple(
                SpeakerLine(start_s=line["start_s"], text=TAG.sub("", line["text"]))
                for line in clip["lines"]
            ),
        )
        for clip in listed["clips"]
    )


def clips_of(kind: SpeakerKind, language: Language) -> list[SpeakerClip]:
    return [
        clip
        for clip in speaker_clips()
        if clip.kind is kind and clip.language == CLIP_LANGUAGE[language]
    ]


def clip_by_file(file: str) -> SpeakerClip | None:
    return next((clip for clip in speaker_clips() if clip.file == file), None)


def with_full_paths(plan: SoundPlan) -> SoundPlan:
    """The plan as a call plays it: each file with its full path. A missing file, or one in
    another format than the call's, raises: the call then fails with a reason before it is
    placed, instead of playing without the sound."""
    for file in {layer.file for layer in plan.layers}:
        with wave.open(str(SOUNDS / file)) as sound:
            if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) != (
                1,
                2,
                SAMPLE_RATE,
            ):
                raise ValueError(f"{file} is not 8 kHz 16-bit mono audio")
    layers = [layer.model_copy(update={"file": str(SOUNDS / layer.file)}) for layer in plan.layers]
    return SoundPlan(layers=layers)


def noise_file(sound: NoiseSound) -> str:
    return f"{sound}.wav"


def gain(db: float, file_dbfs: float) -> float:
    """The gain that puts a file at db relative to the caller's speech."""
    return 10 ** ((SPEECH_DBFS + db - file_dbfs) / 20)


def sound_plan(
    surroundings: Surroundings, language: Language, key: str, duration_s: float
) -> SoundPlan:
    """Every sound behind the caller over duration_s. The same surroundings, language and key
    always give the same plan: a call's key is its scenario version and repeat, so a run of the
    same scenarios again plays the same sounds, and two repeats differ."""
    layers = [
        Layer(
            file=noise_file(s.sound),
            sound=s.sound,
            gain=gain(s.db, NOISE_DBFS),
            start_s=0,
            loop=True,
        )
        for s in surroundings.sounds
    ]
    if surroundings.auto is not None:
        layers += auto_layers(surroundings.auto, key, duration_s)
    if surroundings.speaker is not None:
        layers += speaker_layers(surroundings.speaker, language, key, duration_s)
    return SoundPlan(layers=sorted(layers, key=lambda layer: layer.start_s))


def auto_layers(auto: AutoNoise, key: str, duration_s: float) -> list[Layer]:
    """One sound under the whole call, and others that each play for a few seconds with quiet
    stretches between them."""
    pick = random.Random(f"auto/{auto.seed}/{key}")
    under = pick.choice(list(NoiseSound))
    layers = [
        Layer(
            file=noise_file(under),
            sound=under,
            gain=gain(auto.db, NOISE_DBFS),
            start_s=0,
            loop=True,
        )
    ]
    others = [sound for sound in NoiseSound if sound is not under]
    at = pick.uniform(*AUTO_GAP_S) / 2
    while at < duration_s:
        length = pick.uniform(*AUTO_EVENT_S)
        db = auto.db + pick.randint(-AUTO_SPREAD_DB, AUTO_SPREAD_DB)
        other = pick.choice(others)
        layers.append(
            Layer(
                file=noise_file(other),
                sound=other,
                gain=gain(db, NOISE_DBFS),
                start_s=round(at, 2),
                end_s=round(at + length, 2),
                loop=True,
            )
        )
        at += length + pick.uniform(*AUTO_GAP_S)
    return layers


def speaker_layers(
    speaker: Speaker, language: Language, key: str, duration_s: float
) -> list[Layer]:
    """The speaker's clips one after another from its start, in an order that the key fixes,
    with a short silence between them."""
    clips = clips_of(speaker.kind, language)
    if not clips:
        raise ValueError(f"no {speaker.kind} speaker clips for {language}")
    pick = random.Random(f"speaker/{key}")
    order = pick.sample(clips, len(clips))
    layers = []
    at = speaker.start_s
    while at < duration_s:
        clip = order[len(layers) % len(order)]
        layers.append(
            Layer(
                file=clip.file,
                speaker=speaker.kind,
                gain=gain(speaker.db, SPEECH_DBFS),
                start_s=round(at, 2),
                end_s=round(at + clip.seconds, 2),
                loop=False,
            )
        )
        at += clip.seconds + pick.uniform(*SPEAKER_GAP_S[speaker.kind])
    return layers
