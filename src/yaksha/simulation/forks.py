"""Writes forks of a scenario or a persona from an instruction, for the person to check before
saving: a planner splits the instruction into one change for each fork, then one writer for each
change. Nothing is saved here."""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anyio
import pydantic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yaksha.db.models import Scenario, Voice
from yaksha.domain.agents import AgentConfig, Direction
from yaksha.domain.errors import UnavailableError, ValidationError
from yaksha.domain.forks import ForkRequest
from yaksha.domain.language_models import JsonModel, ModelCallError
from yaksha.domain.languages import Language
from yaksha.domain.names import MAX_NAME_CHARS, fork_name, free_name
from yaksha.domain.personas import PersonaConfig, PersonaCreate
from yaksha.domain.scenarios import Category, ScenarioConfig, ScenarioCreate
from yaksha.domain.surroundings import (
    AutoNoise,
    NoiseSound,
    Sound,
    Speaker,
    SpeakerKind,
    Surroundings,
)
from yaksha.domain.triggers import Trigger, agent_data_names, check_agent_data
from yaksha.domain.voices import VoiceGender, VoiceSettings
from yaksha.simulation import agents, personas, scenarios
from yaksha.simulation.generation_prompts import SCENARIO_SCHEMA, TEXT, TEXTS, strict_object
from yaksha.simulation.persona_drafts import (
    AUTO,
    NOISE_DB,
    SPEAKER_DB,
    SPEAKER_START_S,
    SPEEDS,
)
from yaksha.simulation.templating import render

WRITERS = 4
"""Writer calls at once."""
NONE = "none"
"""A persona fork's word for removing the noise or the speaker; null keeps them."""
CHANGES_SCHEMA = strict_object({"changes": TEXTS})
FORK_SCENARIO_SYSTEM = render("fork_scenario_system.j2")
FORK_PERSONA_SYSTEM = render("fork_persona_system.j2")
MODEL_OFF = "forking with Generate is off: add the LLM provider key in Settings"


def _kept(values: list[str]) -> dict[str, Any]:
    """One of the values, or null for the persona's own."""
    return {"type": ["string", "null"], "enum": [*values, None]}


FORK_PERSONA_SCHEMA = strict_object(
    {
        "name": TEXT,
        "prompt": {"type": ["string", "null"]},
        "language": _kept([language.value for language in Language]),
        "voice_gender": _kept([gender.value for gender in VoiceGender]),
        "speed": _kept(list(SPEEDS)),
        "noise": _kept([*(sound.value for sound in NoiseSound), AUTO, NONE]),
        "noise_level": _kept(list(NOISE_DB)),
        "speaker": _kept([*(kind.value for kind in SpeakerKind), NONE]),
        "unsupported": TEXTS,
    }
)


@dataclass(frozen=True)
class Planned:
    count: int


@dataclass(frozen=True)
class Drafted[T]:
    draft: T


@dataclass(frozen=True)
class Dropped:
    reason: str


type Event[T] = Planned | Drafted[T] | Dropped


async def plan(model: JsonModel, kind: str, original: str, request: ForkRequest) -> list[str]:
    """One distinct change for each fork, at most `request.count`; none when the instruction
    does not say what to change."""
    user = (
        f"## The {kind}\n{original}\n\n## Instruction\n{request.instruction}\n\n"
        f"## Most forks\n{request.count}"
    )
    answer = await model.complete_json(
        system=render("fork_plan_system.j2", kind=kind),
        user=user,
        name="changes",
        schema=CHANGES_SCHEMA,
    )
    changes: list[str] = []
    for change in answer.data.get("changes") or []:
        text = str(change).strip()
        if text and text.lower() not in {seen.lower() for seen in changes}:
            changes.append(text)
    return changes[: request.count]


async def fork_drafts[T](
    model: JsonModel,
    kind: str,
    original: str,
    request: ForkRequest,
    write: Callable[[str], Awaitable[T]],
) -> AsyncGenerator[Event[T]]:
    """The planned count, then each fork as its writer finishes, in the order they finish. A
    writer that fails twice is dropped with its reason. Closing the iterator stops the writers."""
    changes = await plan(model, kind, original, request)
    yield Planned(len(changes))
    gate = asyncio.Semaphore(WRITERS)

    async def one(change: str) -> Drafted[T] | Dropped:
        reason = ""
        for _ in range(2):
            async with gate:
                try:
                    return Drafted(await write(change))
                except (ModelCallError, ValidationError) as error:
                    reason = str(error)
        return Dropped(reason)

    tasks = [asyncio.ensure_future(one(change)) for change in changes]
    try:
        for next_done in asyncio.as_completed(tasks):
            yield await next_done
    finally:
        for task in tasks:
            task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*tasks, return_exceptions=True)


@dataclass(frozen=True)
class ScenarioSource:
    """What the forks of a scenario read, loaded before any model call."""

    id: uuid.UUID
    name: str
    description: str | None
    category: Category
    persona_id: uuid.UUID
    config: ScenarioConfig
    agent_name: str
    agent: AgentConfig
    taken: frozenset[str]
    """The lower-case names of the agent's live scenarios."""

    @property
    def trigger(self) -> Trigger | None:
        outbound = self.agent.outbound
        return outbound.trigger if outbound and self.agent.direction is Direction.OUTBOUND else None

    def text(self) -> str:
        fields = {"name": self.name, "description": self.description or ""}
        return json.dumps({**fields, **self.config.model_dump(mode="json")}, indent=1)


async def scenario_source(
    session: AsyncSession, model: JsonModel | None, scenario_id: uuid.UUID
) -> ScenarioSource:
    if model is None:
        raise UnavailableError(MODEL_OFF)
    scenario = await scenarios.get_scenario(session, scenario_id)
    agent = await agents.get_agent(session, scenario.agent_id)
    taken = await session.scalars(
        select(func.lower(Scenario.name)).where(
            Scenario.agent_id == scenario.agent_id, Scenario.deleted_at.is_(None)
        )
    )
    return ScenarioSource(
        id=scenario.id,
        name=scenario.name,
        description=scenario.description,
        category=scenario.category,
        persona_id=scenario.persona_id,
        config=scenarios.config_of(scenario),
        agent_name=agent.name,
        agent=agents.config_of(agent),
        taken=frozenset(taken),
    )


def scenario_forks(
    model: JsonModel, source: ScenarioSource, request: ForkRequest
) -> AsyncGenerator[Event[ScenarioCreate]]:
    """Forks of the scenario as the API would create them, each with a free name."""
    trigger = source.trigger
    names = sorted(agent_data_names(trigger)) if trigger else []
    agent_text = render("agent.j2", name=source.agent_name, agent=source.agent, agent_data=names)
    named = set(source.taken)

    async def write(change: str) -> ScenarioCreate:
        user = f"{agent_text}\n\n## Scenario\n{source.text()}\n\n## Change\n{change}"
        answer = await model.complete_json(
            system=FORK_SCENARIO_SYSTEM, user=user, name="scenario", schema=SCENARIO_SCHEMA
        )
        try:
            draft = ScenarioCreate.model_validate(
                {
                    **answer.data,
                    "category": source.category,
                    "persona_id": source.persona_id,
                    "first_words": source.config.first_words,
                    "caller": source.config.caller,
                    "agent_data": answer.data.get("agent_data") if names else [],
                    "forked_from_id": source.id,
                }
            )
        except pydantic.ValidationError as error:
            message = error.errors()[0]["msg"]
            raise ValidationError(f"the written fork is not valid: {message}") from error
        if trigger is not None:
            check_agent_data(trigger, draft.to_config())
        name = free_name(draft.name, named)
        named.add(name.lower())
        return draft.model_copy(update={"name": name})

    return fork_drafts(model, "scenario", source.text(), request, write)


def _level(surroundings: Surroundings) -> int:
    """How loud the persona's noise is now: its first sound's level, or the default."""
    if surroundings.auto:
        return surroundings.auto.db
    return surroundings.sounds[0].db if surroundings.sounds else NOISE_DB["normal"]


def changed_surroundings(
    own: Surroundings, noise: str | None, level: str | None, speaker: str | None
) -> Surroundings:
    """The persona's surroundings with only the parts a fork names changed: a new noise keeps
    the current loudness unless a level comes with it, a level alone sets every sound to it,
    and a new speaker keeps the current speaker's volume and start."""
    db = NOISE_DB[level] if level else _level(own)
    sounds, auto = own.sounds, own.auto
    if noise == NONE:
        sounds, auto = (), None
    elif noise == AUTO:
        sounds, auto = (), AutoNoise(db=db)
    elif noise:
        sounds, auto = (Sound(sound=NoiseSound(noise), db=db),), None
    elif level:
        sounds = tuple(sound.model_copy(update={"db": db}) for sound in sounds)
        auto = auto.model_copy(update={"db": db}) if auto else None
    kept = own.speaker
    if speaker == NONE:
        kept = None
    elif speaker:
        kept = Speaker(
            kind=SpeakerKind(speaker),
            db=kept.db if kept else SPEAKER_DB,
            start_s=kept.start_s if kept else SPEAKER_START_S,
        )
    if (noise or speaker) and kept and kept.kind is SpeakerKind.TV:
        sounds = tuple(sound for sound in sounds if sound.sound is not NoiseSound.TV)
    return Surroundings(sounds=sounds, auto=auto, speaker=kept)


@dataclass(frozen=True)
class PersonaSource:
    """What the forks of a persona read, loaded before any model call."""

    id: uuid.UUID
    name: str
    config: PersonaConfig
    taken: frozenset[str]
    """The lower-case names of the live personas."""
    voices: tuple[Voice, ...]
    """The live voices, for a fork in another language or with another gender."""

    def text(self) -> str:
        return json.dumps(
            {"name": self.name, **self.config.model_dump(mode="json", exclude={"sample_line"})},
            indent=1,
        )

    def voice(
        self, language: Language, gender: VoiceGender | None, speed: float, *, asked: bool
    ) -> VoiceSettings:
        """The persona's own voice while the language and the gender stay, else the first
        listed voice that speaks the language, of the gender when it is known. A gender the
        change asked for must be met."""
        own = self.config.voice
        if (language, gender) == (self.config.language, self.config.voice_gender):
            return own.model_copy(update={"speed": speed})
        speaking = [voice for voice in self.voices if language in voice.languages]
        matching = [voice for voice in speaking if gender is None or voice.gender == gender]
        if asked and gender is not None and not matching:
            raise ValidationError(f"no listed {gender.value} voice speaks {language.value}")
        voice = next(iter(matching or speaking), None)
        if voice is None:
            raise ValidationError(f"no listed voice speaks {language.value}")
        return VoiceSettings(
            provider=voice.provider,
            id=voice.provider_voice_id,
            speed=speed,
            stability=own.stability,
        )


async def persona_source(
    session: AsyncSession, model: JsonModel | None, persona_id: uuid.UUID
) -> PersonaSource:
    if model is None:
        raise UnavailableError(MODEL_OFF)
    persona = await personas.get_persona(session, persona_id)
    voices = await session.scalars(
        select(Voice).where(Voice.deleted_at.is_(None)).order_by(Voice.name, Voice.id)
    )
    return PersonaSource(
        id=persona.id,
        name=persona.name,
        config=personas.config_of(persona),
        taken=frozenset(name.lower() for name in await personas.persona_names(session)),
        voices=tuple(voices),
    )


def persona_forks(
    model: JsonModel, source: PersonaSource, request: ForkRequest
) -> AsyncGenerator[Event[PersonaCreate]]:
    """Forks of the persona as the API would create them, each with a free name. Only what
    the model names changes; a change no field can hold drops the fork with the reason."""
    original = source.text()
    own = source.config
    named = set(source.taken)

    async def write(change: str) -> PersonaCreate:
        user = f"## Persona\n{original}\n\n## Change\n{change}"
        if named:
            user += "\n\nNames already used: " + ", ".join(sorted(named))
        data = (
            await model.complete_json(
                system=FORK_PERSONA_SYSTEM, user=user, name="persona", schema=FORK_PERSONA_SCHEMA
            )
        ).data
        unsupported = [str(part).strip() for part in data.get("unsupported") or [] if part]
        if unsupported:
            raise ValidationError(f"not supported: {'; '.join(unsupported)}")
        try:
            language = Language(data["language"]) if data.get("language") else own.language
            gender = (
                VoiceGender(data["voice_gender"]) if data.get("voice_gender") else own.voice_gender
            )
            speed = SPEEDS[data["speed"]] if data.get("speed") else own.voice.speed
            surroundings = changed_surroundings(
                own.surroundings, data.get("noise"), data.get("noise_level"), data.get("speaker")
            )
            written = str(data.get("name") or "").strip()[:MAX_NAME_CHARS]
            name = (
                fork_name(source.name, named)
                if not written or written.lower() == source.name.lower()
                else free_name(written, named)
            )
            fork = PersonaCreate(
                name=name,
                prompt=str(data.get("prompt") or "").strip() or own.prompt,
                language=language,
                voice=source.voice(language, gender, speed, asked=bool(data.get("voice_gender"))),
                surroundings=surroundings,
                sample_line=own.sample_line if language is own.language else None,
                forked_from_id=source.id,
            )
        except (KeyError, ValueError) as error:
            raise ValidationError(f"the written fork is not valid: {error}") from error
        named.add(name.lower())
        return fork

    return fork_drafts(model, "persona", original, request, write)
