import pytest

from yaksha.domain.errors import ValidationError
from yaksha.simulation.curl_import import start_request_from_curl, without_continuations

PLIVO_CX = """curl --location 'https://agentflow.example.com/v1/account/MA0000/flow/c7a9' \\
--header 'Content-Type: application/json' \\
--header 'Authorization: Basic dXNlcjpzZWNyZXQ=' \\
--data '{
  "company_name": "<fill_your_data>",
  "phone_number": "<fill_your_data>"
}'"""


def test_a_post_command_keeps_its_url_headers_and_body_and_calls_yaksha() -> None:
    draft = start_request_from_curl(PLIVO_CX)

    assert (draft.method, draft.url) == (
        "POST",
        "https://agentflow.example.com/v1/account/MA0000/flow/c7a9",
    )
    assert [(pair.name, pair.value) for pair in draft.headers] == [
        ("Authorization", "Basic dXNlcjpzZWNyZXQ=")
    ]
    assert draft.body == {"company_name": "<fill_your_data>", "phone_number": "{{yaksha.number}}"}
    assert draft.number_field == "phone_number" and draft.query == []


def test_a_get_command_moves_the_url_query_into_parameters() -> None:
    draft = start_request_from_curl(
        "curl -u ops:pw 'https://agents.example.com/start?to=%2B1555&campaign=spring'"
    )

    assert (draft.method, draft.url, draft.body) == (
        "GET",
        "https://agents.example.com/start",
        None,
    )
    assert [(pair.name, pair.value) for pair in draft.query] == [
        ("to", "{{yaksha.number}}"),
        ("campaign", "spring"),
    ]
    assert [(pair.name, pair.value) for pair in draft.headers] == [
        ("Authorization", "Basic b3BzOnB3")
    ]


def test_a_body_without_a_number_field_is_kept_as_it_is() -> None:
    draft = start_request_from_curl(
        """curl -X POST https://agents.example.com/calls --data-raw '{"account_id": "a1"}'"""
    )

    assert draft.body == {"account_id": "a1"} and draft.number_field is None


def test_options_read_as_curl_reads_them() -> None:
    draft = start_request_from_curl(
        "curl -sLXPOST https://agents.example.com/sta\\\nrt -H 'Host: x' -H 'Content-Length: 9' "
        "--json '{\"mobile\": 1}'"
    )

    assert (draft.method, draft.url) == ("POST", "https://agents.example.com/start")
    assert [(pair.name, pair.value) for pair in draft.headers] == [("Accept", "application/json")]
    assert draft.body == {"mobile": "{{yaksha.number}}"}


def test_only_the_first_number_parameter_is_replaced() -> None:
    draft = start_request_from_curl("curl 'https://agents.example.com/start?to=1&to=2'")

    assert [(pair.name, pair.value) for pair in draft.query] == [
        ("to", "{{yaksha.number}}"),
        ("to", "2"),
    ]


def test_a_line_end_backslash_joins_lines_except_inside_single_quotes() -> None:
    assert without_continuations("curl 'a\\\nb' c\\\nd \"e\\\r\nf\"") == "curl 'a\\\nb' cd \"ef\""


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("wget https://agents.example.com", "does not start with curl"),
        ("curl -H 'Accept: */*'", "no URL"),
        ("curl --proxy http://p https://agents.example.com", "--proxy"),
        ("curl -X PUT https://agents.example.com -d '{}'", "POST or GET"),
        ("curl -X GET https://agents.example.com -d '{}'", "has no body"),
        ("curl https://agents.example.com -d '{\"a\": }'", "line 1, column 7"),
        ("curl https://agents.example.com -d '[1]'", "not a JSON object"),
        ("curl https://agents.example.com -d @body.json", "from a file"),
        ("curl 'https://agents.example.com", "cannot be read"),
        ("curl -sG https://agents.example.com", "-G"),
        ("curl https://agents.example.com -d '{}' -d '{}'", "more than one body"),
        ("curl https://agents.example.com -H 'A: 1' -H 'a: 2'", "header names must be unique"),
        ("curl https://agents.example.com -H 'Authorization: {{api_key}}'", "api_key"),
        ("curl 'http://['", "URL cannot be read"),
        ('curl https://agents.example.com -d \'{"a": ' + "9" * 5000 + "}'", "cannot be read"),
        ("curl https://agents.example.com -d '{\"a\": NaN}'", "NaN"),
        ('curl https://agents.example.com -d \'{"a": "\\ud800"}\'', "not valid Unicode"),
    ],
    ids=[
        "not curl",
        "no url",
        "unknown option",
        "other method",
        "get with a body",
        "invalid json",
        "not an object",
        "body from a file",
        "open quote",
        "unknown short option in a group",
        "two bodies",
        "duplicate headers",
        "unknown placeholder",
        "bad url",
        "number too long",
        "nan",
        "half a character",
    ],
)
def test_a_command_that_cannot_be_read_says_why(command: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        start_request_from_curl(command)
