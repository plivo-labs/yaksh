from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from yaksh.api.auth import require_token
from yaksh.domain.errors import NotFoundError
from yaksh.domain.languages import Language
from yaksh.domain.surroundings import SoundPlan, Surroundings
from yaksh.simulation.surroundings import SOUNDS, sound_plan

router = APIRouter(prefix="/sounds", tags=["sounds"], dependencies=[Depends(require_token)])

PREVIEW_KEY = "preview"


class PlanPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    surroundings: Surroundings
    language: Language
    duration_s: int = Field(default=60, ge=10, le=600)


@router.post("/plan")
async def preview_plan(command: PlanPreview) -> SoundPlan:
    """The sounds a call with these surroundings plays, as a persona's preview loops them. A call
    plans with its own scenario and repeat, so its random sounds differ from the preview's."""
    return sound_plan(command.surroundings, command.language, PREVIEW_KEY, command.duration_s)


@router.get(
    "/{file:path}", response_class=FileResponse, responses={200: {"content": {"audio/wav": {}}}}
)
async def sound_file(
    file: Annotated[str, Path(pattern=r"^[a-z0-9_]+(/[a-z0-9_]+)?\.wav$")],
) -> FileResponse:
    """A sound file of a plan, 8 kHz 16-bit mono WAV."""
    path = SOUNDS / file
    if not path.is_file():
        raise NotFoundError("sound not found")
    return FileResponse(path, media_type="audio/wav")
