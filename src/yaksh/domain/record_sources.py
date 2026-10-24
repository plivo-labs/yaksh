import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import model_validator

from yaksh.domain.triggers import Endpoint, placeholders


class RecordProvider(StrEnum):
    PLIVO_CX = "plivo_cx"


@dataclass(frozen=True)
class ProviderSpec:
    """The one place, beside its reader, that knows a provider."""

    label: str
    default_url: str
    """The provider's API: where the import and the console start an agent's URL."""
    agent_path: re.Pattern[str]
    url_hint: str
    live_transcript: bool
    """The record's caller turns are the agent's speech-to-text during the call, so they show
    what the agent heard. A transcript made from the recording after the call does not."""


RECORD_PROVIDERS = {
    RecordProvider.PLIVO_CX: ProviderSpec(
        label="Plivo CX",
        default_url="https://api.plivo.com",
        agent_path=re.compile(r"/v1/Account/[A-Za-z0-9]+/AgentFlow/[0-9a-fA-F-]{36}/?"),
        url_hint=(
            "the agent's address in the Plivo API, "
            "https://api.plivo.com/v1/Account/<Auth ID>/AgentFlow/<agent ID>/"
        ),
        live_transcript=True,
    ),
}


class RecordSource(Endpoint):
    """The agent's address in its provider's API, with the headers that read it."""

    provider: RecordProvider

    @model_validator(mode="after")
    def fits_provider(self) -> RecordSource:
        spec = RECORD_PROVIDERS[self.provider]
        if self.url.query or not spec.agent_path.fullmatch(self.url.path or ""):
            raise ValueError(f"the URL must be {spec.url_hint}")
        for header in self.headers:
            for name in placeholders(header.value):
                if not name.startswith("secrets."):
                    raise ValueError(
                        f"an agent record's headers take only {{{{secrets.<NAME>}}}}, "
                        f"not {{{{{name}}}}}"
                    )
        return self
