import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import pydantic
import yaml
from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.db.models import Agent, Persona, PersonaVersion, Scenario, Voice
from yaksh.domain.answering import Answering
from yaksh.domain.errors import ConflictError, NotFoundError, ValidationError
from yaksh.domain.names import fork_name
from yaksh.domain.personas import PersonaConfig, PersonaCreate, PersonaSettings, PersonaUpdate
from yaksh.domain.surroundings import Surroundings
from yaksh.domain.voices import VoiceProvider, VoiceSettings
from yaksh.simulation.voices import builtin_voices, live_voice

NAME_INDEX = "ix_personas_name_live"


def config_of(persona: Persona) -> PersonaConfig:
    return PersonaConfig(
        prompt=persona.prompt,
        language=persona.language,
        voice=VoiceSettings(
            provider=persona.voice_provider,
            id=persona.voice_id,
            model=persona.voice_model,
            speed=persona.voice_speed,
            stability=persona.voice_stability,
        ),
        voice_gender=persona.voice_gender,
        surroundings=Surroundings.model_validate(persona.surroundings),
        sample_line=persona.sample_line,
        answering=Answering.model_validate(persona.answering),
    )


def config_columns(config: PersonaConfig) -> dict[str, Any]:
    return {
        "prompt": config.prompt,
        "language": config.language,
        "voice_provider": config.voice.provider,
        "voice_id": config.voice.id,
        "voice_model": config.voice.model,
        "voice_speed": config.voice.speed,
        "voice_stability": config.voice.stability,
        "voice_gender": config.voice_gender,
        "surroundings": config.surroundings.model_dump(mode="json"),
        "sample_line": config.sample_line,
        "answering": config.answering.model_dump(mode="json"),
    }


def version_row(persona_id: uuid.UUID, version: int, config: PersonaConfig) -> PersonaVersion:
    """A version as stored: the voice's model has its own column, because an older process
    refuses a voice with a field that it does not know."""
    return PersonaVersion(
        persona_id=persona_id,
        version=version,
        config=config.model_dump(mode="json", exclude={"voice": {"model"}}),
        voice_model=config.voice.model,
    )


async def version_config(session: AsyncSession, version: PersonaVersion) -> PersonaConfig:
    """A stored version's config, with its voice's model from its column. A version that an
    older process wrote during a rollout has no model: its voice keeps the persona's model while
    it is the persona's voice. One SELECT reads both, because a persona edit gives such a version
    its model before it changes the persona's voice."""
    config = PersonaConfig.model_validate(version.config)
    model = version.voice_model
    if model is None:
        model, provider, voice_id, persona_model = (
            await session.execute(
                select(
                    PersonaVersion.voice_model,
                    Persona.voice_provider,
                    Persona.voice_id,
                    Persona.voice_model,
                )
                .join(Persona, Persona.id == PersonaVersion.persona_id)
                .where(PersonaVersion.id == version.id)
            )
        ).one()
        if model is None and (provider, voice_id) == (config.voice.provider, config.voice.id):
            model = persona_model
    voice = config.voice.model_copy(update={"model": model})
    return config.model_copy(update={"voice": voice})


def voice_of(config: PersonaConfig) -> tuple[VoiceProvider, str, str | None]:
    return config.voice.provider, config.voice.id, config.voice.model


async def keep_version_models(
    session: AsyncSession, persona_id: uuid.UUID, voice: VoiceSettings
) -> None:
    """A version that an older process wrote without a model speaks with the persona's model
    while it keeps the persona's voice. Before that voice changes, such a version gets the model
    it speaks with now, so a queued call or a retry speaks as before."""
    await session.execute(
        update(PersonaVersion)
        .where(
            PersonaVersion.persona_id == persona_id,
            PersonaVersion.voice_model.is_(None),
            PersonaVersion.config["voice"]["provider"].astext == voice.provider.value,
            PersonaVersion.config["voice"]["id"].astext == voice.id,
        )
        .values(voice_model=voice.model)
    )


def with_listed_voice(settings: dict[str, Any], voice: Voice) -> dict[str, Any]:
    """The settings with the model of the voice's row and its gender from the voices list."""
    listed = {**settings["voice"], "model": voice.model}
    return {**settings, "voice": listed, "voice_gender": voice.gender}


def apply_config(persona: Persona, config: PersonaConfig) -> None:
    for column, value in config_columns(config).items():
        setattr(persona, column, value)


def validate_config(data: dict[str, Any]) -> PersonaConfig:
    try:
        return PersonaConfig.model_validate(data)
    except pydantic.ValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc


async def flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if NAME_INDEX in str(exc.orig):
            raise ConflictError("name is already used by another persona") from exc
        raise


async def existing_persona(
    session: AsyncSession, persona_id: uuid.UUID, *, lock: bool = False
) -> Persona:
    persona = await session.get(Persona, persona_id, with_for_update=lock, populate_existing=lock)
    if persona is None:
        raise NotFoundError("persona not found")
    return persona


async def get_persona(
    session: AsyncSession, persona_id: uuid.UUID, *, lock: bool = False
) -> Persona:
    persona = await existing_persona(session, persona_id, lock=lock)
    if persona.deleted_at is not None:
        raise NotFoundError("persona not found")
    return persona


async def live_personas(
    session: AsyncSession, persona_ids: Sequence[uuid.UUID], *, share_lock: bool = False
) -> dict[uuid.UUID, Persona]:
    """The live personas with these ids, all of them, or NotFoundError naming a missing one.
    With share_lock they are share-locked in id order: edits and deletes wait, references do
    not."""
    query = select(Persona).where(Persona.id.in_(persona_ids)).order_by(Persona.id)
    if share_lock:
        query = query.with_for_update(read=True)
    found = {row.id: row for row in await session.scalars(query) if row.deleted_at is None}
    for persona_id in persona_ids:
        if persona_id not in found:
            raise NotFoundError(f"persona {persona_id} not found")
    return found


async def create_persona(session: AsyncSession, command: PersonaCreate) -> Persona:
    settings = command.settings()
    voice = await live_voice(session, settings.voice)
    config = validate_config(with_listed_voice(settings.model_dump(), voice))
    if command.forked_from_id is not None:
        await existing_persona(session, command.forked_from_id)
    persona = Persona(name=command.name, current_version=1, forked_from_id=command.forked_from_id)
    apply_config(persona, config)
    session.add(persona)
    await flush(session)
    session.add(version_row(persona.id, 1, config))
    await session.commit()
    return persona


FORK_NAME_TRIES = 3
"""Personas have no row to lock, so a fork whose free name was taken meanwhile tries again."""


async def fork_persona(session: AsyncSession, persona_id: uuid.UUID) -> Persona:
    """A copy of the persona under a free "… (fork)" name, at version 1. A built-in persona's
    copy is not built in."""
    source = await get_persona(session, persona_id)
    # Read now: a conflict rolls the session back, which expires the row.
    source_id, source_name = source.id, source.name
    settings = config_of(source).model_dump(exclude={"voice_gender"})
    for attempt in range(FORK_NAME_TRIES):
        taken = {name.lower() for name in await persona_names(session)}
        command = PersonaCreate(
            **settings, name=fork_name(source_name, taken), forked_from_id=source_id
        )
        try:
            return await create_persona(session, command)
        except ConflictError:
            if attempt == FORK_NAME_TRIES - 1:
                raise
    raise AssertionError("unreachable")


async def persona_names(session: AsyncSession) -> list[str]:
    """The names of the live personas, in order."""
    rows = await session.scalars(
        select(Persona.name).where(Persona.deleted_at.is_(None)).order_by(Persona.name)
    )
    return list(rows)


async def list_personas(
    session: AsyncSession, *, offset: int, limit: int
) -> tuple[list[Persona], int]:
    query = select(Persona).where(Persona.deleted_at.is_(None))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(Persona.created_at.desc(), Persona.id).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def update_persona(
    session: AsyncSession, persona_id: uuid.UUID, update: PersonaUpdate
) -> Persona:
    """Rename in place; a changed config writes the next version. Only a voice that differs
    from the stored one must be in the voices list, so a persona whose voice was deleted
    later can still be saved while it keeps that voice."""
    persona = await get_persona(session, persona_id, lock=True)
    changes = update.changes()
    if "name" in changes:
        persona.name = changes.pop("name")
    if changes:
        current = config_of(persona)
        merged = {**current.model_dump(), **changes}
        voice = update.voice
        if voice is not None:
            same_voice = (voice.provider, voice.id) == (current.voice.provider, current.voice.id)
            if same_voice and voice.model in (None, current.voice.model):
                merged["voice"] = {**merged["voice"], "model": current.voice.model}
            else:
                merged = with_listed_voice(merged, await live_voice(session, voice))
        new = validate_config(merged)
        if new != current:
            if voice_of(new) != voice_of(current):
                await keep_version_models(session, persona.id, current.voice)
            apply_config(persona, new)
            persona.current_version += 1
            session.add(version_row(persona.id, persona.current_version, new))
    await flush(session)
    await session.refresh(persona)
    await session.commit()
    return persona


async def delete_persona(session: AsyncSession, persona_id: uuid.UUID) -> None:
    """Refused while a live scenario runs with the persona. Saving a scenario locks the persona
    row too, so the count cannot miss one being saved."""
    persona = await get_persona(session, persona_id, lock=True)
    used = await session.scalar(
        select(func.count()).where(Scenario.persona_id == persona.id, Scenario.deleted_at.is_(None))
    )
    if used:
        raise ConflictError(
            "1 scenario uses this persona; give it another persona first"
            if used == 1
            else f"{used} scenarios use this persona; give them another persona first"
        )
    persona.deleted_at = datetime.now(UTC)
    await session.commit()


async def persona_scenarios(
    session: AsyncSession, persona_id: uuid.UUID
) -> list[tuple[Scenario, str]]:
    """The live scenarios that use the persona, with their agent's name, by agent then scenario
    name: the ones that keep it from being deleted."""
    persona = await get_persona(session, persona_id)
    rows = await session.execute(
        select(Scenario, Agent.name)
        .join(Agent, Agent.id == Scenario.agent_id)
        .where(Scenario.persona_id == persona.id, Scenario.deleted_at.is_(None))
        .order_by(Agent.name, Scenario.name, Scenario.id)
    )
    return [(scenario, agent_name) for scenario, agent_name in rows.tuples()]


async def list_versions(
    session: AsyncSession, persona_id: uuid.UUID, *, offset: int, limit: int
) -> tuple[list[PersonaVersion], int]:
    persona = await existing_persona(session, persona_id)
    query = select(PersonaVersion).where(PersonaVersion.persona_id == persona.id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(PersonaVersion.version.desc()).offset(offset).limit(limit)
    )
    return list(rows), total or 0


async def get_version(session: AsyncSession, persona_id: uuid.UUID, version: int) -> PersonaVersion:
    persona = await existing_persona(session, persona_id)
    row = await session.scalar(
        select(PersonaVersion).where(
            PersonaVersion.persona_id == persona.id, PersonaVersion.version == version
        )
    )
    if row is None:
        raise NotFoundError("persona version not found")
    return row


class BuiltinPersona(PersonaSettings):
    """A persona file in the package. Its voice must be a built-in voice."""

    name: str = Field(min_length=1, max_length=80)


def builtin_personas() -> list[tuple[str, BuiltinPersona]]:
    """The personas that ship in the package, keyed by file name."""
    folder = files("yaksh.simulation") / "builtin_personas"
    return [
        (
            entry.name.removesuffix(".yaml"),
            BuiltinPersona.model_validate(yaml.safe_load(entry.read_text(encoding="utf-8"))),
        )
        for entry in sorted(folder.iterdir(), key=lambda entry: entry.name)
        if entry.name.endswith(".yaml")
    ]


async def seed_builtin_personas(session: AsyncSession) -> list[str]:
    """Insert each built-in persona that has no row yet and return their keys. An edited or
    deleted built-in keeps its row, and a user persona with the same name is kept, so nothing
    a user changed comes back. Run it after the voice seed: the gender comes from the voice's
    row, even a deleted one."""
    shipped = {
        (voice.provider, voice.provider_voice_id): voice.provider.traits.chosen(voice.model).id
        for voice in builtin_voices()
    }
    present = set(
        await session.scalars(select(Persona.builtin_key).where(Persona.builtin_key.is_not(None)))
    )
    seeded: list[str] = []
    for key, builtin in builtin_personas():
        voice_key = (builtin.voice.provider, builtin.voice.id)
        if voice_key not in shipped:
            raise RuntimeError(f"built-in persona {key} uses a voice that is not a built-in voice")
        if key in present:
            continue
        voice = await session.scalar(
            select(Voice)
            .where(
                Voice.provider == builtin.voice.provider,
                Voice.provider_voice_id == builtin.voice.id,
            )
            .order_by(
                Voice.model.is_not_distinct_from(shipped[voice_key]).desc(),
                Voice.deleted_at.is_not(None),
                Voice.created_at.desc(),
            )
            .limit(1)
        )
        if voice is None:
            raise RuntimeError(f"seed the built-in voices before built-in persona {key}")
        config = validate_config(with_listed_voice(builtin.model_dump(exclude={"name"}), voice))
        persona_id = await session.scalar(
            insert(Persona)
            .values(name=builtin.name, builtin_key=key, current_version=1, **config_columns(config))
            .on_conflict_do_nothing()
            .returning(Persona.id)
        )
        if persona_id is not None:
            session.add(version_row(persona_id, 1, config))
            seeded.append(key)
    await session.commit()
    return seeded
