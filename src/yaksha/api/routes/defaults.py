from fastapi import APIRouter
from pydantic import BaseModel

from yaksha.api.deps import AppSettingsDep
from yaksha.domain.languages import Language
from yaksha.simulation.languages import LANGUAGES

router = APIRouter(tags=["defaults"])


class Defaults(BaseModel):
    """What the server uses for a field that a request leaves out."""

    max_duration_s: int
    max_turns: int
    max_retries: int
    """Of a run."""
    first_words: dict[Language, str]
    """What the caller says first, by the persona's language, when a scenario sets none."""


@router.get("/defaults")
async def defaults(settings: AppSettingsDep) -> Defaults:
    return Defaults(
        max_duration_s=settings.limits.default_max_duration_s,
        max_turns=settings.limits.default_max_turns,
        max_retries=settings.limits.default_max_retries,
        first_words={language: policy.first_words for language, policy in LANGUAGES.items()},
    )
