from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from truman.config import Settings
from truman.simulation.personas import VoiceCatalogs


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_voice_catalogs(request: Request) -> VoiceCatalogs:
    return request.app.state.voice_catalogs


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
VoiceCatalogsDep = Annotated[VoiceCatalogs, Depends(get_voice_catalogs)]
