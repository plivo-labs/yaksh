"""Reads an agent file from another platform into a draft agent. Each platform's file is read at
fixed paths, and the whole file becomes the agent's config, which the judges read."""

import json
from typing import Any, NoReturn

from yaksha.domain.agent_import import AgentDraft, ImportProvider
from yaksha.domain.agents import MAX_CONFIG_CHARS
from yaksha.domain.errors import UnrecognizedFileError, ValidationError
from yaksha.domain.languages import Language


def import_agent(content: str) -> AgentDraft:
    if len(content) > MAX_CONFIG_CHARS:
        raise ValidationError("the file is larger than a config can be")
    data = parse(content)
    if not is_plivo_cx(data):
        raise UnrecognizedFileError("Yaksha does not know this file's format")
    return AgentDraft(
        provider=ImportProvider.PLIVO_CX,
        name=text(data.get("name")),
        external_id=text(data.get("flowId")),
        language=plivo_cx_language(data["agentSettings"]),
        config=content,
    )


def parse(content: str) -> Any:
    """Strict JSON. No field Yaksha reads is a number, so numbers are read as floats: an integer
    longer than Python's 4300-digit limit is still valid JSON."""
    try:
        return json.loads(content, parse_int=float, parse_constant=not_json)
    except json.JSONDecodeError as error:
        raise ValidationError(
            f"the file is not valid JSON: line {error.lineno}, column {error.colno}: {error.msg}"
        ) from None


def not_json(constant: str) -> NoReturn:
    raise ValidationError(f"the file is not valid JSON: {constant} is not a JSON value")


def is_plivo_cx(data: Any) -> bool:
    """The Plivo CX console's agent download: the flow's ID, its nodes and its settings."""
    return (
        isinstance(data, dict)
        and isinstance(data.get("flowId"), str)
        and isinstance(data.get("nodes"), list)
        and isinstance(data.get("agentSettings"), dict)
    )


def plivo_cx_language(settings: dict[str, Any]) -> Language:
    """The first of the flow's languages, such as en-IN in "en-IN,hi". A language Yaksha does not
    speak yet becomes English."""
    voice = settings.get("voice_ai_config")
    codes = voice.get("language") if isinstance(voice, dict) else None
    first = codes.split(",")[0].strip().lower() if isinstance(codes, str) else ""
    return Language.HI if first.startswith("hi") else Language.EN


def text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        value.encode()
    except UnicodeEncodeError:
        # A JSON escape such as \ud800 decodes to half a character, which no response can carry.
        raise ValidationError("the file has a name or ID that is not valid Unicode") from None
    return value.strip() or None
