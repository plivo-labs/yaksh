"""Reads an agent file from another platform into a draft agent. Each platform's file is read at
fixed paths, and the whole file becomes the agent's config, which the judges read."""

import json
import logging
from collections.abc import Awaitable, Generator, Iterable
from contextlib import contextmanager
from typing import Any, NoReturn

from yaksha.domain.agent_import import AgentDraft, ImportProvider
from yaksha.domain.agents import MAX_CONFIG_CHARS
from yaksha.domain.errors import (
    NotFoundError,
    ProviderCallError,
    UnavailableError,
    UnrecognizedFileError,
    ValidationError,
)
from yaksha.domain.languages import AgentLanguage
from yaksha.simulation.curl_import import FILL, ScenarioNames

log = logging.getLogger(__name__)


def import_agent(content: str) -> AgentDraft:
    if len(content) > MAX_CONFIG_CHARS:
        raise ValidationError("the file is larger than a config can be")
    data = parse(content)
    if not is_plivo_cx(data):
        raise UnrecognizedFileError("Yaksha does not know this file's format")
    languages, note = plivo_cx_languages(data["agentSettings"])
    return AgentDraft(
        provider=ImportProvider.PLIVO_CX,
        name=text(data.get("name")),
        external_id=text(data.get("flowId")),
        languages=languages,
        language_note=note,
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


def plivo_cx_languages(settings: dict[str, Any]) -> tuple[list[AgentLanguage], str | None]:
    """The flow's languages, such as en-IN and hi in "en-IN,hi"."""
    voice = settings.get("voice_ai_config")
    codes = voice.get("language") if isinstance(voice, dict) else None
    return agent_languages(codes.split(",") if isinstance(codes, str) else [])


def agent_languages(codes: Iterable[Any]) -> tuple[list[AgentLanguage], str | None]:
    """A provider's language codes as the languages Yaksha knows, in their order, and a note
    that names the codes it does not know. No code at all is the providers' default, English."""
    given = [code.strip() for code in codes if isinstance(code, str) and code.strip()]
    if not given:
        return [AgentLanguage.EN_US], None
    known: list[AgentLanguage] = []
    unknown: list[str] = []
    for code in given:
        language = agent_language(code)
        if language is None:
            unknown.append(code)
        elif language not in known:
            known.append(language)
    if not unknown:
        return known, None
    return (
        known,
        f"Yaksha does not know the language {', '.join(unknown)}. Choose the agent's languages",
    )


def agent_language(code: str) -> AgentLanguage | None:
    """A code such as hi-IN, en_in or en; en alone is en-US. None for a code Yaksha does not
    know, such as multi or en-NZ."""
    tag = code.replace("_", "-").lower()
    if tag == "en":
        return AgentLanguage.EN_US
    for language in AgentLanguage:
        if language.value.lower() == tag:
            return language
    base = tag.split("-")[0]
    return AgentLanguage(base) if base in AgentLanguage else None


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


def without(value: Any, keys: frozenset[str]) -> Any:
    """`value` without `keys` at any depth, schemas too: a provider keeps credentials in them. The
    property names of a JSON schema stay: they are what a tool takes, such as a headers field."""
    if isinstance(value, dict):
        return {
            key: (
                {name: without(item_, keys) for name, item_ in item.items()}
                if key == "properties" and isinstance(item, dict)
                else without(item, keys)
            )
            for key, item in value.items()
            if key not in keys
        }
    if isinstance(value, list):
        return [without(item, keys) for item in value]
    return value


async def unless_missing(read: Awaitable[dict[str, Any]]) -> dict[str, Any] | None:
    """An agent can name a tool that was deleted; the provider answers 404 for it."""
    try:
        return await read
    except ProviderCallError as error:
        if error.status == 404:
            return None
        raise


def scenario_variables(names: Iterable[str]) -> dict[str, str]:
    """Each of an agent's variables as agent data that every scenario fills, named for itself."""
    taken = ScenarioNames()
    variables = {name: taken.fill(FILL, (name,)) for name in names}
    taken.check()
    return variables


@contextmanager
def provider_errors(provider: str, *, refused: str, forbidden: str) -> Generator[None]:
    """A provider's failed call as an error the person can act on. The provider's reply stays out
    of the message: the client sees only its status."""
    try:
        yield
    except ProviderCallError as error:
        log.warning("%s import call failed: %s", provider, error)
        match error.status:
            case 401:
                raise ValidationError(refused) from None
            case 403:
                raise ValidationError(forbidden) from None
            case 404:
                raise NotFoundError(f"{provider} has no agent or tool with this ID") from None
            case 429:
                raise UnavailableError(
                    f"{provider} refused more requests for now; wait a minute, then try again"
                ) from None
            case None:
                raise UnavailableError(
                    f"Yaksha could not reach {provider}; try again later"
                ) from None
            case status:
                raise UnavailableError(
                    f"{provider} answered with status {status}; try again later"
                ) from None
    except ValueError as error:
        log.warning("%s import call answered with an unexpected body: %s", provider, error)
        raise UnavailableError(f"{provider} answered with something that is not JSON") from None
