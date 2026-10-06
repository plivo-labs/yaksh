from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

E164 = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{6,14}$")]


class AccountNumber(BaseModel):
    """A number on the Plivo account, as its Number API lists it."""

    model_config = ConfigDict(frozen=True)

    number: E164
    alias: str | None = None
    region: str | None = None
    voice: bool = True
    application_id: str | None = None


class PlivoApplication(BaseModel):
    """The Plivo Application that receives the calls to the numbers linked to it."""

    model_config = ConfigDict(frozen=True)

    app_id: str
    name: str
    answer_url: str
    answer_method: str
    hangup_url: str
    hangup_method: str

    def problems(self, public_url: str) -> list[str]:
        """Why this Application cannot send test calls to a worker at public_url; empty when
        it can."""
        base = public_url.rstrip("/")
        expected = {
            "answer URL": (self.answer_url, f"{base}/incoming"),
            "hangup URL": (self.hangup_url, f"{base}/incoming/hangup"),
            "answer method": (self.answer_method.upper(), "POST"),
            "hangup method": (self.hangup_method.upper(), "POST"),
        }
        return [
            f"Plivo application {self.name} has {label} {actual!r}; set it to {wanted!r}"
            for label, (actual, wanted) in expected.items()
            if actual != wanted
        ]
