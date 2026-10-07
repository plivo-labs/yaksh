"""Drafts an agent's brief from its config, for the person to check and change."""

from yaksha.domain.agents import MAX_BRIEF_CHARS, MIN_BRIEF_CHARS
from yaksha.domain.errors import UnavailableError, ValidationError
from yaksha.domain.language_models import JsonModel, ModelCallError
from yaksha.simulation.generation_prompts import TEXT, strict_object
from yaksha.simulation.templating import render

MODEL_OFF = "drafting a brief is off: add the LLM provider key in Settings"
BRIEF_SYSTEM = render("brief_system.j2")
BRIEF_SCHEMA = strict_object({"brief": TEXT})
MAX_SOURCE_CHARS = 200_000
"""A longer config is cut: a brief needs what the agent is for, which the start shows."""


async def draft_brief(model: JsonModel | None, config: str) -> str:
    if model is None:
        raise UnavailableError(MODEL_OFF)
    if not config.strip():
        raise ValidationError("the config is empty, so there is nothing to draft the brief from")
    answer = await model.complete_json(
        system=BRIEF_SYSTEM, user=config[:MAX_SOURCE_CHARS], name="brief", schema=BRIEF_SCHEMA
    )
    brief = str(answer.data.get("brief", "")).strip()
    if not MIN_BRIEF_CHARS <= len(brief) <= MAX_BRIEF_CHARS:
        raise ModelCallError(f"the model gave a brief of {len(brief)} characters", temporary=True)
    return brief
