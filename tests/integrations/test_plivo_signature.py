import pytest

from yaksha.integrations.plivo_signature import is_signed

TOKEN = "test-auth-token"
CALL = {"To": ["+15716535187"], "From": ["+19153188577"], "CallUUID": ["abc-123"]}


@pytest.mark.parametrize(
    ("method", "url", "params", "nonce", "expected"),
    [
        (
            "POST",
            "https://yaksha.example/incoming",
            CALL,
            "nonce-4",
            "LgfIyefhTWH8KWP1wOfvtX+msnGuqFS5Z1MJiQNdbn8=",
        ),
        (
            "POST",
            "https://yaksha.example/answer/7f2c?x=1#rc=5",
            {**CALL, "Direction": ["inbound"]},
            "nonce-1",
            "wPk3Z0e7UMwkSp2bkITZXpKBYdPL27jSZ1FfQ53C6vY=",
        ),
        (
            "POST",
            "https://yaksha.example/callbacks/7f2c",
            {},
            "n3",
            "/OpVCWLzL44XIshc0Suq5DN0UzuZ9Q9fJcem9Dekl1I=",
        ),
        (
            "GET",
            "wss://yaksha.example/stream/7f2c",
            {},
            "nonce-2",
            "3+S2U/IlfB5i0N8o5sMwQgEKvqjTHo+w6eHNR92+1wA=",
        ),
    ],
    ids=["webhook", "query and fragment", "no fields", "websocket upgrade"],
)
def test_signatures_computed_by_the_plivo_sdk_are_accepted(
    method: str, url: str, params: dict[str, list[str]], nonce: str, expected: str
) -> None:
    """The expected values come from the Plivo Python SDK's validate_v3_signature code."""
    headers = {"x-plivo-signature-v3-nonce": nonce, "x-plivo-signature-v3": expected}

    assert is_signed(headers, TOKEN, method, url, params)
    assert not is_signed(headers, "another-token", method, url, params)


def test_any_listed_signature_from_either_header_is_accepted() -> None:
    url = "https://yaksha.example/incoming"
    good = "LgfIyefhTWH8KWP1wOfvtX+msnGuqFS5Z1MJiQNdbn8="

    main_account = {"x-plivo-signature-v3-nonce": "nonce-4", "x-plivo-signature-ma-v3": good}
    rotated = {"x-plivo-signature-v3-nonce": "nonce-4", "x-plivo-signature-v3": f"old, {good}"}
    no_nonce = {"x-plivo-signature-v3": good}

    assert is_signed(main_account, TOKEN, "POST", url, CALL)
    assert is_signed(rotated, TOKEN, "POST", url, CALL)
    assert not is_signed(no_nonce, TOKEN, "POST", url, CALL)


def test_a_malformed_signature_is_refused_without_hiding_a_valid_one() -> None:
    url = "https://yaksha.example/incoming"
    good = "LgfIyefhTWH8KWP1wOfvtX+msnGuqFS5Z1MJiQNdbn8="
    garbled = {"x-plivo-signature-v3-nonce": "nonce-4", "x-plivo-signature-v3": "\xff"}

    assert not is_signed(garbled, TOKEN, "POST", url, CALL)
    assert is_signed({**garbled, "x-plivo-signature-ma-v3": good}, TOKEN, "POST", url, CALL)
