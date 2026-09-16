from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from truman.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
