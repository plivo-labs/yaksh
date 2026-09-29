import pytest

from truman.integrations.plivo_signature import is_signed

TOKEN = "test-auth-token"
CALL = {"To": ["+15716535187"], "From": ["+19153188577"], "CallUUID": ["abc-123"]}


@pytest.mark.parametrize(
    ("method", "url", "params", "nonce", "expected"),
    [
        (
            "POST",
            "https://truman.example/incoming",
            CALL,
            "nonce-4",
            "96J2SSsDEPuRMtYWF6hm1j/jrUiX8Iebp0QqFe/eqDQ=",
        ),
        (
            "POST",
            "https://truman.example/answer/7f2c?x=1#rc=5",
            {**CALL, "Direction": ["inbound"]},
            "nonce-1",
            "yQtkmaKQ1rKPrcOOLfi0X8aM9ZYJdqV+r+le8UP3RoA=",
        ),
        (
            "POST",
            "https://truman.example/callbacks/7f2c",
            {},
            "n3",
            "mzVaShXAb+ujoHh7iF5tI+D4q77ABlIrTAJdkxTP+eY=",
        ),
        (
            "GET",
            "wss://truman.example/stream/7f2c",
            {},
            "nonce-2",
            "d9TyhdfDqqrCSHpGC+UdPqXsot647gU3YA14d5r2Srs=",
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
    url = "https://truman.example/incoming"
    good = "96J2SSsDEPuRMtYWF6hm1j/jrUiX8Iebp0QqFe/eqDQ="

    main_account = {"x-plivo-signature-v3-nonce": "nonce-4", "x-plivo-signature-ma-v3": good}
    rotated = {"x-plivo-signature-v3-nonce": "nonce-4", "x-plivo-signature-v3": f"old, {good}"}
    no_nonce = {"x-plivo-signature-v3": good}

    assert is_signed(main_account, TOKEN, "POST", url, CALL)
    assert is_signed(rotated, TOKEN, "POST", url, CALL)
    assert not is_signed(no_nonce, TOKEN, "POST", url, CALL)


def test_a_malformed_signature_is_refused_without_hiding_a_valid_one() -> None:
    url = "https://truman.example/incoming"
    good = "96J2SSsDEPuRMtYWF6hm1j/jrUiX8Iebp0QqFe/eqDQ="
    garbled = {"x-plivo-signature-v3-nonce": "nonce-4", "x-plivo-signature-v3": "\xff"}

    assert not is_signed(garbled, TOKEN, "POST", url, CALL)
    assert is_signed({**garbled, "x-plivo-signature-ma-v3": good}, TOKEN, "POST", url, CALL)
