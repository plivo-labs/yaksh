from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from yaksh.config import Settings
from yaksh.domain.files import FileStore
from yaksh.domain.language_models import JsonModel
from yaksh.domain.settings import AppSettings
from yaksh.simulation.voices import VoiceClients


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_app_settings(request: Request) -> AppSettings:
    """The stored settings, read again when they changed since this process last read them."""
    return await request.app.state.source.current()


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_voice_clients(
    request: Request, settings: Annotated[AppSettings, Depends(get_app_settings)]
) -> VoiceClients:
    return request.app.state.providers.voice_clients(settings)


def get_generation_model(
    request: Request, settings: Annotated[AppSettings, Depends(get_app_settings)]
) -> JsonModel | None:
    return request.app.state.providers.generation_model(settings)


def get_brief_model(
    request: Request, settings: Annotated[AppSettings, Depends(get_app_settings)]
) -> JsonModel | None:
    return request.app.state.providers.brief_model(settings)


def get_file_store(request: Request) -> FileStore:
    return request.app.state.file_store


SettingsDep = Annotated[Settings, Depends(get_settings)]
AppSettingsDep = Annotated[AppSettings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
VoiceClientsDep = Annotated[VoiceClients, Depends(get_voice_clients)]
GenerationModelDep = Annotated[JsonModel | None, Depends(get_generation_model)]
BriefModelDep = Annotated[JsonModel | None, Depends(get_brief_model)]
FileStoreDep = Annotated[FileStore, Depends(get_file_store)]
