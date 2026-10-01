from fastapi import APIRouter
from pydantic import BaseModel

from truman.api.deps import SettingsDep

router = APIRouter(tags=["defaults"])


class Defaults(BaseModel):
    """What the server uses for a field that a request leaves out."""

    max_duration_s: int
    max_retries: int
    """Of a run."""


@router.get("/defaults")
async def defaults(settings: SettingsDep) -> Defaults:
    return Defaults(
        max_duration_s=settings.default_max_duration_s, max_retries=settings.default_max_retries
    )
