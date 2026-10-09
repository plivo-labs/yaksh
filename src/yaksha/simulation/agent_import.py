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
    """The first of the flow's languages, such as en-IN in "en-IN,hi"."""
    voice = settings.get("voice_ai_config")
    codes = voice.get("language") if isinstance(voice, dict) else None
    return language(codes.split(",")[0] if isinstance(codes, str) else None)


def language(code: Any) -> Language:
    """A provider's language code, such as hi or en-IN. A language Yaksha does not speak yet
    becomes English."""
    first = code.strip().lower() if isinstance(code, str) else ""
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


NOT_BEHAVIOR = frozenset({"code_body"})
"""The source code of a tool action; its description and parameters stay."""
CONTRACTS = frozenset({"parameters", "properties", "payload_format"})
"""Schemas and payload shapes, such as these and any field named like request_body_schema, kept
exactly: an empty value or a field named code_body in one is part of what a tool takes."""
REDACTED = "***REDACTED***"


def pruned(value: Any) -> Any:
    """`value` without empty values, redacted secrets or tool source, at any depth except inside a
    schema; False and 0 stay, because they mean something."""
    if isinstance(value, dict):
        kept = {
            key: item if contract(key) else pruned(item)
            for key, item in value.items()
            if key not in NOT_BEHAVIOR
        }
        return {key: item for key, item in kept.items() if contract(key) or not empty(item)}
    if isinstance(value, list):
        return [item for item in (pruned(item) for item in value) if not empty(item)]
    return value


def empty(value: Any) -> bool:
    return value is None or value in ("", REDACTED) or value == [] or value == {}


def contract(key: str) -> bool:
    return key in CONTRACTS or key.endswith("schema")
