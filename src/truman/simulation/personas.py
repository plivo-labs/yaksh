import uuid
from collections.abc import Mapping
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

from truman.db.models import Persona, PersonaVersion
from truman.domain.errors import ConflictError, NotFoundError, UnavailableError, ValidationError
from truman.domain.personas import (
    Language,
    PersonaConfig,
    PersonaCreate,
    PersonaUpdate,
    Voice,
    VoiceGender,
    VoiceProvider,
)
from truman.domain.voices import VoiceCatalog, VoiceInfo
from truman.simulation.languages import LANGUAGES

NAME_INDEX = "ix_personas_name_live"

type VoiceCatalogs = Mapping[VoiceProvider, VoiceCatalog]


def config_of(persona: Persona) -> PersonaConfig:
    return PersonaConfig(
        prompt=persona.prompt,
        language=persona.language,
        voice=Voice(
            provider=persona.voice_provider,
            id=persona.voice_id,
            speed=persona.voice_speed,
            stability=persona.voice_stability,
        ),
        voice_gender=persona.voice_gender,
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
    }


def apply_config(persona: Persona, config: PersonaConfig) -> None:
    for column, value in config_columns(config).items():
        setattr(persona, column, value)


def validate_config(data: dict[str, Any]) -> PersonaConfig:
    try:
        return PersonaConfig.model_validate(data)
    except pydantic.ValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc


def catalog_for(catalogs: VoiceCatalogs, provider: VoiceProvider) -> VoiceCatalog:
    catalog = catalogs.get(provider)
    if catalog is None:
        raise UnavailableError(f"voice provider {provider} is not set up")
    return catalog


async def check_voice(catalogs: VoiceCatalogs, voice: Voice) -> VoiceGender | None:
    """Confirm the voice exists and return its gender as the provider labels it."""
    info = await catalog_for(catalogs, voice.provider).get_voice(voice.id)
    if info is None:
        raise ValidationError(f"voice {voice.id} was not found on the {voice.provider} account")
    label = (info.gender or "").lower()
    return VoiceGender(label) if label in VoiceGender else None


async def preview_voice(catalogs: VoiceCatalogs, voice: Voice, language: Language) -> bytes:
    """The language's sample sentence, spoken with the voice, settings and audio a call uses."""
    audio = await catalog_for(catalogs, voice.provider).speak(
        voice, language, LANGUAGES[language].sample
    )
    if audio is None:
        raise ValidationError(f"voice {voice.id} was not found on the {voice.provider} account")
    return audio


async def list_voices(
    catalogs: VoiceCatalogs,
    provider: VoiceProvider,
    *,
    offset: int,
    limit: int,
    language: Language | None = None,
) -> tuple[list[VoiceInfo], int]:
    """A page of the provider's voices; with a language, only those verified for it."""
    voices = await catalog_for(catalogs, provider).list_voices(language)
    return voices[offset : offset + limit], len(voices)


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


async def create_persona(
    session: AsyncSession, catalogs: VoiceCatalogs, command: PersonaCreate
) -> Persona:
    settings = command.settings()
    gender = await check_voice(catalogs, settings.voice)
    config = PersonaConfig.model_validate({**settings.model_dump(), "voice_gender": gender})
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
    session: AsyncSession,
    catalogs: VoiceCatalogs,
    persona_id: uuid.UUID,
    update: PersonaUpdate,
) -> Persona:
    """Rename in place; a changed config writes the next version. A new voice is checked
    after the read transaction ends and before the row is locked, so neither a connection
    nor a lock is held across a call to the provider. The voice gender always comes from
    data about the voice being saved: the provider's answer for a new voice, or the gender
    read together with the same voice id, never the locked row a concurrent change may have
    moved to another voice."""
    persona = await get_persona(session, persona_id)
    current_voice = (persona.voice_provider, persona.voice_id)
    gender = persona.voice_gender
    await session.rollback()
    if update.voice is not None and (update.voice.provider, update.voice.id) != current_voice:
        gender = await check_voice(catalogs, update.voice)
    changes = update.changes()
    persona = await get_persona(session, persona_id, lock=True)
    if "name" in changes:
        persona.name = changes.pop("name")
    if changes:
        current = config_of(persona)
        merged = {**current.model_dump(), **changes}
        if update.voice is not None:
            merged["voice_gender"] = gender
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
    persona = await get_persona(session, persona_id, lock=True)
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


class BuiltinPersona(PersonaConfig):
    """A persona file in the package. It states the voice gender itself, because the seed
    does not ask the provider."""

    name: str = Field(min_length=1, max_length=80)
    voice_gender: VoiceGender | None


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
    a user changed comes back. Premade voices exist on every account, so no voice check runs."""
    seeded: list[str] = []
    for key, builtin in builtin_personas():
        config = PersonaConfig.model_validate(builtin.model_dump(exclude={"name"}))
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
