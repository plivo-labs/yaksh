from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from truman.config import Settings
from truman.simulation.voices import VoiceClients


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_voice_clients(request: Request) -> VoiceClients:
    return request.app.state.voice_clients


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
VoiceClientsDep = Annotated[VoiceClients, Depends(get_voice_clients)]
