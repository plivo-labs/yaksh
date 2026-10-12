"""Plivo's V3 request signature: HMAC-SHA256 of the called URL, the sorted parameters and a
nonce, keyed by the auth token. Built to match the Plivo SDK's validate_v3_signature."""

import base64
import hashlib
import hmac
from collections.abc import Mapping, Sequence
from urllib.parse import parse_qs, urlsplit, urlunsplit

SIGNATURE_HEADERS = ("x-plivo-signature-v3", "x-plivo-signature-ma-v3")
NONCE_HEADER = "x-plivo-signature-v3-nonce"


def signed_text(method: str, url: str, params: Mapping[str, Sequence[str]]) -> str:
    """What Plivo signs. The fragment is dropped. A GET appends its sorted query; a POST
    appends `?`, the query, a `.` when both exist, then each parameter as key+value."""
    parts = urlsplit(url)
    base = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    query = "&".join(
        f"{key}={value}"
        for key, values in sorted(parse_qs(parts.query, keep_blank_values=True).items())
        for value in sorted(values)
    )
    if method == "GET" or not params:
        return f"{base}?{query}" if query else base
    body = "".join(
        f"{key}{value}" for key, values in sorted(params.items()) for value in sorted(values)
    )
    return f"{base}?{query}.{body}" if query else f"{base}?{body}"


def signature(auth_token: str, text: str, nonce: str) -> str:
    digest = hmac.new(auth_token.encode(), f"{text}.{nonce}".encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def is_signed(
    headers: Mapping[str, str],
    auth_token: str,
    method: str,
    url: str,
    params: Mapping[str, Sequence[str]],
) -> bool:
    """True when either Plivo signature header (account or main account) matches. A header can
    list several signatures, one per active token."""
    nonce = headers.get(NONCE_HEADER)
    if not nonce:
        return False
    expected = signature(auth_token, signed_text(method, url, params), nonce)
    return any(
        hmac.compare_digest(expected.encode(), candidate.strip().encode())
        for name in SIGNATURE_HEADERS
        for candidate in headers.get(name, "").split(",")
        if candidate.strip()
    )
