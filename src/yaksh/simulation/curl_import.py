"""Reads a cURL command, such as the one an agent platform shows for starting an outbound call,
into a start request. The command is split as a shell would split it, never run."""

import base64
import json
import re
import shlex
from typing import Any, NoReturn
from urllib.parse import parse_qsl, urlsplit

import pydantic

from yaksh.domain.agent_import import Pair, StartRequestDraft
from yaksh.domain.errors import ValidationError
from yaksh.domain.scenarios import MAX_FACT_NAME_CHARS, MAX_FACTS, normalized
from yaksh.domain.triggers import PLACEHOLDER, RESERVED_HEADERS, Trigger, TriggerMethod

NUMBER = "{{yaksh.number}}"
FILL = "<fill_your_data>"
"""What Plivo CX's "Copy cURL" puts in each field for the person to fill."""
DATA = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--json"}
WITH_VALUE = {"-X", "--request", "-H", "--header", "-u", "--user", "--url", *DATA}
# Options that do not change the request Yaksh sends.
IGNORED = {
    "-L", "--location", "-s", "--silent", "-S", "--show-error", "-i", "--include", "-v",
    "--verbose", "-k", "--insecure", "--compressed", "-f", "--fail",
}  # fmt: skip
NUMBER_NAME = re.compile(r"phone|mobile|^to$|^number$|^to_number$|^destination$", re.IGNORECASE)


def start_request_from_curl(command: str) -> StartRequestDraft:
    words = split(command)
    if not words or words[0] != "curl":
        raise ValidationError("the command does not start with curl")
    method: str | None = None
    url: str | None = None
    headers: list[Pair] = []
    data: str | None = None
    json_data = False
    for option, value in options(words[1:]):
        if option is None:
            url = url or value
        elif option in ("-X", "--request"):
            method = value.upper()
        elif option in ("-H", "--header"):
            headers.append(header(value))
        elif option in ("-u", "--user"):
            token = base64.b64encode(value.encode()).decode()
            headers.append(Pair(name="Authorization", value=f"Basic {token}"))
        elif option == "--url":
            url = value
        else:
            if data is not None:
                raise ValidationError("the command has more than one body; join them into one")
            data, json_data = value, option == "--json"
    if not url:
        raise ValidationError("the command has no URL")
    if json_data and not any(pair.name.lower() == "accept" for pair in headers):
        headers.append(Pair(name="Accept", value="application/json"))
    found = draft(method or ("POST" if data is not None else "GET"), url, headers, data)
    check(found)
    return found


def split(command: str) -> list[str]:
    try:
        return shlex.split(without_continuations(command))
    except ValueError as error:
        raise ValidationError(f"the command cannot be read: {error}") from None


def without_continuations(command: str) -> str:
    """Removes each backslash at the end of a line, as a shell does, except inside single quotes,
    where a shell keeps it."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        char = command[i]
        if char == "\\" and quote != "'":
            rest = command[i + 1 : i + 3]
            if rest.startswith("\n") or rest == "\r\n":
                i += 1 + len("\r\n" if rest == "\r\n" else "\n")
                continue
            out.append(command[i : i + 2])
            i += 2
            continue
        if quote is None and char in "'\"":
            quote = char
        elif char == quote:
            quote = None
        out.append(char)
        i += 1
    return "".join(out)


def options(words: list[str]) -> list[tuple[str | None, str]]:
    """Each option with its value, and each other word as (None, word). A group of short options
    such as -sXPOST reads as -s -X POST."""
    found: list[tuple[str | None, str]] = []
    rest = iter(words)

    def value_of(option: str, attached: str | None) -> str:
        value = attached if attached is not None else next(rest, None)
        if value is None:
            raise ValidationError(f"the curl option {option} has no value")
        return value

    for word in rest:
        if not word.startswith("-") or word == "-":
            found.append((None, word))
        elif word.startswith("--"):
            name, equals, attached = word.partition("=")
            known(name)
            if name in WITH_VALUE:
                found.append((name, value_of(name, attached if equals else None)))
        else:
            letters = word[1:]
            for at, letter in enumerate(letters):
                name = f"-{letter}"
                known(name)
                if name in WITH_VALUE:
                    found.append((name, value_of(name, letters[at + 1 :] or None)))
                    break
    return found


def known(option: str) -> None:
    if option not in WITH_VALUE and option not in IGNORED:
        raise ValidationError(f"Yaksh does not read the curl option {option}")


def header(value: str) -> Pair:
    name, colon, text = value.partition(":")
    if not colon or not name.strip():
        raise ValidationError(f"the header {value!r} has no name")
    return Pair(name=name.strip(), value=text.strip())


def draft(method: str, url: str, headers: list[Pair], data: str | None) -> StartRequestDraft:
    if method not in TriggerMethod:
        raise ValidationError(f"a start request is POST or GET, not {method}")
    # The HTTP client sets these headers itself.
    headers = [pair for pair in headers if pair.name.lower() not in RESERVED_HEADERS]
    if method == TriggerMethod.GET:
        if data is not None:
            raise ValidationError("a GET start request has no body; put its values in the URL")
        try:
            parts = urlsplit(url)
        except ValueError as error:
            raise ValidationError(f"the URL cannot be read: {error}") from None
        query = [Pair(name=k, value=v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
        at = next((i for i, pair in enumerate(query) if NUMBER_NAME.search(pair.name)), None)
        if at is not None:
            query[at] = Pair(name=query[at].name, value=NUMBER)
        names = ScenarioNames([pair.value for pair in query], [pair.value for pair in headers])
        query = [Pair(name=pair.name, value=names.fill(pair.value, (pair.name,))) for pair in query]
        names.check()
        return StartRequestDraft(
            method=TriggerMethod.GET,
            url=parts._replace(query="").geturl(),
            headers=headers,
            query=query,
            body=None,
            number_field=None if at is None else query[at].name,
        )
    body = json_body(data)
    field = next((name for name in body if NUMBER_NAME.search(name)), None)
    if field is not None:
        body[field] = NUMBER
    return StartRequestDraft(
        method=TriggerMethod.POST,
        url=url,
        headers=headers,
        query=[],
        body=scenario_body(body, headers),
        number_field=field,
    )


class ScenarioNames:
    """Turns each field still marked to fill into a value that every scenario gives,
    {{agent_data.<name>}}: scenario generation writes one that fits the caller, and a scenario
    without it is refused. A field is named by its path, such as lead_source or items_0; names
    are made safe for a placeholder and unique, and `check` refuses more values than a scenario
    holds."""

    def __init__(self, *used: Any) -> None:
        """`used` holds the request's other parts: the agent data names they already use count
        toward the limit, and a new name never takes one of them."""
        self.taken: set[str] = agent_data_names_in(used)

    def fill(self, item: Any, path: tuple[str, ...] = ()) -> Any:
        if isinstance(item, dict):
            return {key: self.fill(child, (*path, key)) for key, child in item.items()}
        if isinstance(item, list):
            return [self.fill(child, (*path, str(at))) for at, child in enumerate(item)]
        return f"{{{{agent_data.{self.name(path)}}}}}" if item == FILL else item

    def name(self, path: tuple[str, ...]) -> str:
        parts = [" ".join(part.replace("{", "").replace("}", "").split()) for part in path]
        base = "_".join(part for part in parts if part)[:MAX_FACT_NAME_CHARS] or "field"
        name, count = base, 1
        while normalized(name) in self.taken:
            count += 1
            suffix = f"_{count}"
            name = base[: MAX_FACT_NAME_CHARS - len(suffix)] + suffix
        self.taken.add(normalized(name))
        return name

    def check(self) -> None:
        if len(self.taken) > MAX_FACTS:
            raise ValidationError(
                f"the start request has {len(self.taken)} fields to fill, and a scenario holds at "
                f"most {MAX_FACTS} values; fill some of them in the command"
            )


def scenario_body(body: dict[str, Any], headers: list[Pair]) -> dict[str, Any]:
    names = ScenarioNames(body, [pair.value for pair in headers])
    filled = names.fill(body)
    names.check()
    return filled


def agent_data_names_in(value: Any) -> set[str]:
    """The agent data names that placeholders anywhere in `value` use, as scenarios compare them."""
    if isinstance(value, dict):
        return set().union(*(agent_data_names_in(item) for item in value.values()))
    if isinstance(value, list | tuple):
        return set().union(*(agent_data_names_in(item) for item in value))
    if not isinstance(value, str):
        return set()
    found = (match.strip().partition(".") for match in PLACEHOLDER.findall(value))
    return {normalized(rest) for kind, _, rest in found if kind == "agent_data" and rest.strip()}


def json_body(data: str | None) -> dict[str, Any]:
    if data is None:
        return {}
    if data.startswith("@"):
        raise ValidationError("the body is read from a file; paste the JSON itself")
    try:
        body = json.loads(data, parse_constant=not_json)
    except json.JSONDecodeError as error:
        raise ValidationError(
            f"the body is not valid JSON: line {error.lineno}, column {error.colno}: {error.msg}"
        ) from None
    except ValueError as error:
        # Python refuses to read an integer longer than 4300 digits.
        raise ValidationError(f"the body cannot be read: {error}") from None
    if not isinstance(body, dict):
        raise ValidationError("the body is not a JSON object")
    try:
        json.dumps(body, ensure_ascii=False).encode()
    except UnicodeEncodeError:
        raise ValidationError("the body has text that is not valid Unicode") from None
    return body


def not_json(constant: str) -> NoReturn:
    raise ValidationError(f"the body is not valid JSON: {constant} is not a JSON value")


def check(found: StartRequestDraft) -> None:
    """Refuses a request that the agent could not be saved with, and says why, before the form
    is filled with it."""
    try:
        Trigger.model_validate(
            {
                "method": found.method,
                "url": found.url,
                "headers": [pair.model_dump() for pair in found.headers],
                "query": [pair.model_dump() for pair in found.query],
                "body": found.body,
            }
        )
    except pydantic.ValidationError as error:
        first = error.errors()[0]
        place = ".".join(str(part) for part in first["loc"])
        reason = first["msg"].removeprefix("Value error, ")
        raise ValidationError(f"{place}: {reason}" if place else reason) from None
