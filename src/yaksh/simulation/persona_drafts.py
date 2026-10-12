"""Writes a new persona from a short line, for the person to check and change before saving."""

from typing import Any

from yaksh.domain.errors import UnavailableError
from yaksh.domain.language_models import JsonModel, ModelCallError
from yaksh.domain.languages import Language
from yaksh.domain.names import MAX_NAME_CHARS
from yaksh.domain.personas import PersonaDraft, PersonaIdea
from yaksh.domain.surroundings import (
    AutoNoise,
    NoiseSound,
    Sound,
    Speaker,
    SpeakerKind,
    Surroundings,
)
from yaksh.domain.voices import VoiceGender
from yaksh.simulation.generation_prompts import TEXT, TEXTS, strict_object
from yaksh.simulation.templating import render

MODEL_OFF = "writing a persona is off: add the LLM provider key in Settings"
PERSONA_SYSTEM = render("persona_system.j2")
MIN_BEHAVIOR_CHARS = 40
MAX_BEHAVIOR_CHARS = 4000
SPEEDS = {"slow": 0.85, "normal": 1.0, "fast": 1.15}
AUTO = "mixed"
NOISE_DB = {"soft": -18, "normal": -10, "loud": -4}
""""normal" is as loud as a noise the person adds in the console."""
SPEAKER_DB = -6
SPEAKER_START_S = 5


def _choice(values: list[str]) -> dict[str, Any]:
    return {"type": ["string", "null"], "enum": [*values, None]}


PERSONA_SCHEMA = strict_object(
    {
        "name": TEXT,
        "prompt": TEXT,
        "language": {"type": "string", "enum": [language.value for language in Language]},
        "voice_gender": {"type": "string", "enum": [gender.value for gender in VoiceGender]},
        "speed": {"type": "string", "enum": list(SPEEDS)},
        "noise": _choice([*(sound.value for sound in NoiseSound), AUTO]),
        "noise_level": {"type": "string", "enum": list(NOISE_DB)},
        "speaker": _choice([kind.value for kind in SpeakerKind]),
        "left_out": TEXTS,
    }
)


async def draft_persona(
    model: JsonModel | None, source: PersonaIdea, taken_names: list[str]
) -> PersonaDraft:
    """`taken_names` are the existing personas' names, which the new one must not repeat."""
    if model is None:
        raise UnavailableError(MODEL_OFF)
    user = f"Line: {source.idea}"
    if taken_names:
        user += "\nNames already used: " + ", ".join(taken_names)
    answer = await model.complete_json(
        system=PERSONA_SYSTEM, user=user, name="persona", schema=PERSONA_SCHEMA
    )
    data = answer.data
    name = str(data.get("name") or "").strip()[:MAX_NAME_CHARS]
    prompt = str(data.get("prompt") or "").strip()
    if not name or not MIN_BEHAVIOR_CHARS <= len(prompt) <= MAX_BEHAVIOR_CHARS:
        raise ModelCallError("the model gave no usable persona", temporary=True)
    try:
        surroundings = _surroundings(data)
        return PersonaDraft(
            name=name,
            prompt=prompt,
            language=Language(data.get("language")),
            voice_gender=VoiceGender(data.get("voice_gender")),
            speed=SPEEDS[str(data.get("speed"))],
            surroundings=surroundings,
            left_out=[
                str(part).strip() for part in data.get("left_out") or [] if str(part).strip()
            ],
        )
    except (KeyError, ValueError) as error:
        raise ModelCallError(
            f"the model gave a persona out of range: {error}", temporary=True
        ) from error


def _surroundings(data: dict[str, Any]) -> Surroundings:
    noise, speaker = data.get("noise"), data.get("speaker")
    if speaker == SpeakerKind.TV and noise == NoiseSound.TV:
        noise = None  # one TV: the second speaker already plays it
    db = NOISE_DB[str(data.get("noise_level"))]
    return Surroundings(
        sounds=(Sound(sound=NoiseSound(noise), db=db),) if noise and noise != AUTO else (),
        auto=AutoNoise(db=db) if noise == AUTO else None,
        speaker=(
            Speaker(kind=SpeakerKind(speaker), db=SPEAKER_DB, start_s=SPEAKER_START_S)
            if speaker
            else None
        ),
    )
