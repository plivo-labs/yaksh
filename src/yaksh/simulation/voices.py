import uuid
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from importlib.resources import files

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.db.models import Voice
from yaksh.domain.errors import ConflictError, NotFoundError, UnavailableError, ValidationError
from yaksh.domain.languages import Language
from yaksh.domain.voices import (
    PROVIDER_VOICE_ID,
    ProviderVoice,
    VoiceClient,
    VoiceCreate,
    VoiceGender,
    VoiceProvider,
    VoiceSettings,
    VoiceUpdate,
)
from yaksh.simulation.languages import LANGUAGES

LIVE_INDEX = "ix_voices_provider_voice_live"

type VoiceClients = Mapping[VoiceProvider, VoiceClient]


def client_for(clients: VoiceClients, provider: VoiceProvider) -> VoiceClient:
    client = clients.get(provider)
    if client is None:
        raise UnavailableError(f"voice provider {provider.label} is not set up")
    return client


def ordered(languages: Collection[Language]) -> list[Language]:
    return [language for language in Language if language in languages]


async def lookup_voice(
    clients: VoiceClients, provider: VoiceProvider, provider_voice_id: str
) -> ProviderVoice:
    if not provider.traits.lookup:
        raise ValidationError(f"{provider.label} has no voice lookup; enter the voice's details")
    found = await client_for(clients, provider).get_voice(provider_voice_id)
    if found is None:
        raise ValidationError(
            f"voice {provider_voice_id} was not found on the {provider.label} account. "
            "A Voice Library voice must be added to the account first."
        )
    return found


async def preview_voice(
    clients: VoiceClients,
    voice: VoiceSettings,
    language: Language,
    sample_line: str | None = None,
) -> bytes:
    """The sample line, else the language's sample sentence, spoken through the same
    text-to-speech, voice settings and 8 kHz format as a call. A provider that cannot speak it,
    as with a voice it does not know, gives its reason."""
    client = client_for(clients, voice.provider)
    try:
        return await client.speak(voice, language, sample_line or LANGUAGES[language].sample)
    except UnavailableError as error:
        raise ValidationError(str(error)) from None


async def flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if LIVE_INDEX in str(exc.orig):
            raise ConflictError("this voice is already in the voices list") from exc
        raise


async def create_voice(session: AsyncSession, clients: VoiceClients, command: VoiceCreate) -> Voice:
    """A provider with lookup describes the voice; any other must speak a line in it first, so
    a voice ID the provider does not know is never listed."""
    if command.provider.traits.lookup:
        found = await lookup_voice(clients, command.provider, command.provider_voice_id)
    else:
        language = ordered(command.languages)[0]
        try:
            await client_for(clients, command.provider).speak(
                VoiceSettings(provider=command.provider, id=command.provider_voice_id),
                language,
                LANGUAGES[language].sample,
            )
        except UnavailableError as error:
            raise ValidationError(f"not saved: {error}") from None
        found = ProviderVoice(
            id=command.provider_voice_id,
            name=command.name or command.provider_voice_id,
            gender=command.gender,
            accent=command.accent,
        )
    voice = Voice(
        provider=command.provider,
        provider_voice_id=command.provider_voice_id,
        name=command.name or found.name,
        gender=found.gender,
        accent=found.accent,
        languages=ordered(command.languages),
        listed_languages=ordered(found.listed_languages),
        builtin=False,
    )
    session.add(voice)
    await flush(session)
    await session.commit()
    return voice


async def get_voice(session: AsyncSession, voice_id: uuid.UUID, *, lock: bool = False) -> Voice:
    voice = await session.get(Voice, voice_id, with_for_update=lock, populate_existing=lock)
    if voice is None or voice.deleted_at is not None:
        raise NotFoundError("voice not found")
    return voice


async def live_voice(session: AsyncSession, settings: VoiceSettings) -> Voice:
    """The live row for the voice a persona uses; a persona can only use a listed voice."""
    voice = await session.scalar(
        select(Voice).where(
            Voice.provider == settings.provider,
            Voice.provider_voice_id == settings.id,
            Voice.deleted_at.is_(None),
        )
    )
    if voice is None:
        raise ValidationError(f"voice {settings.id} is not in the voices list")
    return voice


async def list_voices(
    session: AsyncSession, *, offset: int, limit: int, language: Language | None = None
) -> tuple[list[Voice], int]:
    query = select(Voice).where(Voice.deleted_at.is_(None))
    if language is not None:
        query = query.where(Voice.languages.contains([language]))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(Voice.name, Voice.id).offset(offset).limit(limit))
    return list(rows), total or 0


async def update_voice(session: AsyncSession, voice_id: uuid.UUID, update: VoiceUpdate) -> Voice:
    voice = await get_voice(session, voice_id, lock=True)
    changes = update.changes()
    if "name" in changes:
        voice.name = changes["name"]
    if "languages" in changes:
        voice.languages = ordered(changes["languages"])
    await session.flush()
    await session.refresh(voice)
    await session.commit()
    return voice


async def delete_voice(session: AsyncSession, voice_id: uuid.UUID) -> None:
    voice = await get_voice(session, voice_id, lock=True)
    voice.deleted_at = datetime.now(UTC)
    await session.commit()


class BuiltinVoice(BaseModel):
    """A voice in the package file. It holds what the provider says about the voice, because
    the seed does not ask the provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: VoiceProvider
    provider_voice_id: str = Field(pattern=PROVIDER_VOICE_ID)
    name: str = Field(min_length=1, max_length=80)
    gender: VoiceGender | None
    accent: str | None
    languages: frozenset[Language] = Field(min_length=1)
    listed_languages: frozenset[Language]


def builtin_voices() -> list[BuiltinVoice]:
    text = (files("yaksh.simulation") / "builtin_voices.yaml").read_text(encoding="utf-8")
    return [BuiltinVoice.model_validate(entry) for entry in yaml.safe_load(text)]


async def seed_builtin_voices(session: AsyncSession) -> list[str]:
    """Insert each built-in voice that has no row, live or deleted, and return their names.
    An edited or deleted built-in voice keeps its row, so nothing a user changed comes back."""
    seeded: list[str] = []
    for builtin in builtin_voices():
        known = await session.scalar(
            select(
                exists().where(
                    Voice.provider == builtin.provider,
                    Voice.provider_voice_id == builtin.provider_voice_id,
                )
            )
        )
        if known:
            continue
        inserted = await session.scalar(
            insert(Voice)
            .values(
                provider=builtin.provider,
                provider_voice_id=builtin.provider_voice_id,
                name=builtin.name,
                gender=builtin.gender,
                accent=builtin.accent,
                languages=ordered(builtin.languages),
                listed_languages=ordered(builtin.listed_languages),
                builtin=True,
            )
            .on_conflict_do_nothing()
            .returning(Voice.id)
        )
        if inserted is not None:
            seeded.append(builtin.name)
    await session.commit()
    return seeded
