import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

import pydantic
import yaml
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from truman.db.models import Persona, PersonaVersion, Scenario, Voice
from truman.domain.background_noise import BackgroundNoise
from truman.domain.errors import ConflictError, NotFoundError, ValidationError
from truman.domain.personas import PersonaConfig, PersonaCreate, PersonaSettings, PersonaUpdate
from truman.domain.voices import VoiceSettings
from truman.simulation.voices import builtin_voices, live_voice

NAME_INDEX = "ix_personas_name_live"


def config_of(persona: Persona) -> PersonaConfig:
    return PersonaConfig(
        prompt=persona.prompt,
        language=persona.language,
        voice=VoiceSettings(
            provider=persona.voice_provider,
            id=persona.voice_id,
            speed=persona.voice_speed,
            stability=persona.voice_stability,
        ),
        voice_gender=persona.voice_gender,
        background_noise=BackgroundNoise(
            sound=persona.background_noise_sound, level=persona.background_noise_level
        ),
    )


def config_columns(config: PersonaConfig) -> dict[str, Any]:
    return {
        "prompt": config.prompt,
        "language": config.language,
        "voice_provider": config.voice.provider,
        "voice_id": config.voice.id,
        "voice_speed": config.voice.speed,
        "voice_stability": config.voice.stability,
        "voice_gender": config.voice_gender,
        "background_noise_sound": config.background_noise.sound,
        "background_noise_level": config.background_noise.level,
    }


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
    config = PersonaConfig.model_validate({**settings.model_dump(), "voice_gender": voice.gender})
    persona = Persona(name=command.name, current_version=1)
    apply_config(persona, config)
    session.add(persona)
    await flush(session)
    session.add(
        PersonaVersion(persona_id=persona.id, version=1, config=config.model_dump(mode="json"))
    )
    await session.commit()
    return persona


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
        if voice is not None and (voice.provider, voice.id) != (
            current.voice.provider,
            current.voice.id,
        ):
            merged["voice_gender"] = (await live_voice(session, voice)).gender
        new = validate_config(merged)
        if new != current:
            apply_config(persona, new)
            persona.current_version += 1
            session.add(
                PersonaVersion(
                    persona_id=persona.id,
                    version=persona.current_version,
                    config=new.model_dump(mode="json"),
                )
            )
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
    folder = files("truman.simulation") / "builtin_personas"
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
    shipped = {(voice.provider, voice.provider_voice_id) for voice in builtin_voices()}
    seeded: list[str] = []
    for key, builtin in builtin_personas():
        if (builtin.voice.provider, builtin.voice.id) not in shipped:
            raise RuntimeError(f"built-in persona {key} uses a voice that is not a built-in voice")
        voice = await session.scalar(
            select(Voice)
            .where(
                Voice.provider == builtin.voice.provider,
                Voice.provider_voice_id == builtin.voice.id,
            )
            .order_by(Voice.deleted_at.is_not(None), Voice.created_at.desc())
            .limit(1)
        )
        if voice is None:
            raise RuntimeError(f"seed the built-in voices before built-in persona {key}")
        config = PersonaConfig.model_validate(
            {**builtin.model_dump(exclude={"name"}), "voice_gender": voice.gender}
        )
        persona_id = await session.scalar(
            insert(Persona)
            .values(name=builtin.name, builtin_key=key, current_version=1, **config_columns(config))
            .on_conflict_do_nothing()
            .returning(Persona.id)
        )
        if persona_id is not None:
            session.add(
                PersonaVersion(
                    persona_id=persona_id, version=1, config=config.model_dump(mode="json")
                )
            )
            seeded.append(key)
    await session.commit()
    return seeded
