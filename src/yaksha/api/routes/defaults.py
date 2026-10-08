from fastapi import APIRouter
from pydantic import BaseModel

from yaksha.api.deps import SettingsDep
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
    sample_lines: dict[Language, str]
    """What a voice preview says, by language, when the persona sets no sample line."""


@router.get("/defaults")
async def defaults(settings: SettingsDep) -> Defaults:
    return Defaults(
        max_duration_s=settings.default_max_duration_s,
        max_turns=settings.default_max_turns,
        max_retries=settings.default_max_retries,
        first_words={language: policy.first_words for language, policy in LANGUAGES.items()},
        sample_lines={language: policy.sample for language, policy in LANGUAGES.items()},
    )
