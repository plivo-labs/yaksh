"""A provider's own voices, to pick one to add: the request to its REST API, and the search and
pages that Yaksh does itself for a provider that sends its whole list or has none."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import aiohttp

from yaksh.diagnostics import describe_exception
from yaksh.domain.errors import UnavailableError
from yaksh.domain.voices import CatalogPage, CatalogQuery, ProviderVoice

PAGE_SIZE = 30
TIMEOUT = aiohttp.ClientTimeout(total=15)


def rest_address(url: str) -> str:
    """The REST API at the host of an address, https for wss or https: a key goes only to the
    host it was checked at, and never over plain HTTP from a TLS address."""
    scheme, rest = url.split("://", 1)
    return f"{'https' if scheme in ('wss', 'https') else 'http'}://{rest.split('/', 1)[0]}"


def websocket_address(url: str) -> str:
    """The websocket API at an address, wss for https or wss, as an address is often given
    with https; with no trailing slash, as a service appends its path."""
    scheme, rest = url.split("://", 1)
    return f"{'wss' if scheme in ('wss', 'https') else 'ws'}://{rest.rstrip('/')}"


async def get_json(
    provider: str, url: str, params: Mapping[str, str], headers: Mapping[str, str]
) -> Any:
    """Raises UnavailableError with the provider's reason, never with the key."""
    try:
        async with (
            aiohttp.ClientSession(headers=dict(headers), timeout=TIMEOUT) as session,
            session.get(url, params=dict(params)) as response,
        ):
            status, text = response.status, await response.text()
    except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as error:
        raise UnavailableError(f"{provider} did not answer: {describe_exception(error)}") from None
    if status >= 400:
        raise UnavailableError(f"{provider} refused the voice list with {status}: {text[:200]}")
    try:
        return json.loads(text)
    except ValueError:
        raise UnavailableError(f"{provider} sent a voice list that is not JSON") from None


def page_of(voices: Sequence[ProviderVoice], query: CatalogQuery) -> CatalogPage:
    """The query's page of the voices that match it; the cursor is where the page starts."""
    search = (query.search or "").casefold()
    matching = [
        voice
        for voice in voices
        if (not search or search in voice.name.casefold() or search in voice.id.casefold())
        and (query.language is None or query.language in voice.listed_languages)
        and (query.gender is None or voice.gender is query.gender)
    ]
    start = int(query.cursor) if query.cursor and query.cursor.isdigit() else 0
    end = start + PAGE_SIZE
    return CatalogPage(
        items=matching[start:end], next_cursor=str(end) if end < len(matching) else None
    )
