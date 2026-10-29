"""Who answers an outbound test call: the persona, or the voicemail or call screener of its
phone. A machine plays fixed recordings and never hears the agent; the persona talks only once
it picks up."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class AnsweredBy(StrEnum):
    CALLER = "caller"
    VOICEMAIL = "voicemail"
    SCREENER = "screener"


class Voicemail(StrEnum):
    IPHONE = "iphone"
    PIXEL = "pixel"
    CARRIER = "carrier"
    CARRIER_NO_TONE = "carrier_no_tone"
    MAILBOX_FULL = "mailbox_full"
    """A line that the mailbox is full, then it hangs up: no greeting, no recording."""


class Screener(StrEnum):
    IPHONE = "iphone"
    PIXEL_CALL_ASSIST = "pixel_call_assist"
    GOOGLE_2018 = "google_2018"
    SAMSUNG = "samsung"
    TRUECALLER = "truecaller"


class AfterScreening(StrEnum):
    """What the persona does once its screener has heard the agent."""

    PICKS_UP = "picks_up"
    VOICEMAIL = "voicemail"
    """Its voicemail answers: the greeting, the tone, the recording."""
    REPLY = "reply"
    """The screener says a reply, then hangs up."""
    DECLINES = "declines"
    """The screener hangs up after the hold."""


VOICEMAIL_LABELS = {
    Voicemail.IPHONE: "iPhone voicemail",
    Voicemail.PIXEL: "Pixel voicemail",
    Voicemail.CARRIER: "Carrier voicemail",
    Voicemail.CARRIER_NO_TONE: "Carrier voicemail, no tone",
    Voicemail.MAILBOX_FULL: "Mailbox full",
}
SCREENER_LABELS = {
    Screener.IPHONE: "iPhone call screening",
    Screener.PIXEL_CALL_ASSIST: "Pixel Call Assist",
    Screener.GOOGLE_2018: "Google Call Screen (2018)",
    Screener.SAMSUNG: "Samsung call screening",
    Screener.TRUECALLER: "Truecaller Assistant",
}

Greeting = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
"""As long as a voice preview's sample line, so the persona page can play it."""


class Answering(BaseModel):
    """The persona's phone, for the calls that a run sends to its voicemail or call screener."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    voicemail: Voicemail = Voicemail.IPHONE
    greeting: Greeting | None = None
    """Said in the persona's voice before the tone; None plays the voicemail's standard
    greeting. A full mailbox plays neither."""
    screener: Screener = Screener.IPHONE
    after_screening: AfterScreening = AfterScreening.PICKS_UP

    @property
    def picks_up(self) -> bool:
        """The persona picks up after its call screener."""
        return self.after_screening is AfterScreening.PICKS_UP


def reaches(
    answered_by: AnsweredBy, *, picked_up: bool, voicemail_answered: bool
) -> frozenset[AnsweredBy]:
    """Who the agent talked to, from what the call recorded: after a screener, the persona when
    it picked up, and the voicemail when a voicemail line played. A screener that ended the call,
    or an agent that hung up on it, reached only the screener."""
    if answered_by is not AnsweredBy.SCREENER:
        return frozenset({answered_by})
    after = {AnsweredBy.CALLER} if picked_up else set()
    if voicemail_answered:
        after.add(AnsweredBy.VOICEMAIL)
    return frozenset({AnsweredBy.SCREENER, *after})


def plays_scenario(answered_by: AnsweredBy, *, picked_up: bool) -> bool:
    """The persona talks on the call, so the scenario's criteria and the caller check apply."""
    return answered_by is AnsweredBy.CALLER or (answered_by is AnsweredBy.SCREENER and picked_up)


class MachineLine(StrEnum):
    """Machine audio on the call. A spoken line is a caller turn; the tone is not."""

    GREETING = "greeting"
    TONE = "tone"
    MAILBOX_FULL = "mailbox_full"
    SCREENER = "screener"
    REPLY = "reply"


class MachineClip(BaseModel):
    """A recorded line: an 8 kHz 16-bit mono WAV file, by its full path, and its words."""

    model_config = ConfigDict(frozen=True)

    line: MachineLine
    file: str
    text: str


class VoicemailPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    greeting: MachineClip | None
    """The recorded line that starts the voicemail; None when the persona says its own
    greeting."""
    own_greeting: str | None
    """Said in the persona's voice."""
    tone: str | None
    """The tone's file; None for a voicemail that starts to record with no tone."""
    full: bool = False
    """The mailbox is full: the greeting line is all it plays."""
    tone_gap_s: float
    silence_end_s: float
    """The recording stops when the agent has been silent this long."""
    recording_limit_s: float


class ScreenerPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    prompt: MachineClip
    follow_ups: list[MachineClip]
    acknowledgement: MachineClip
    reply: MachineClip
    hold_s: float
    answer_wait_s: float
    """How long the screener waits for the agent's answer after a question."""
    limit_s: float | None
    """The screener ends the call at this time, counted from the answer."""
    after: AfterScreening


class AnsweringPlan(BaseModel):
    """What answers the call and when: a screener, a voicemail, or a screener that passes the
    call on to the voicemail."""

    model_config = ConfigDict(frozen=True)

    start_delay_s: float
    """From the answer to the first line."""
    screener: ScreenerPlan | None = None
    voicemail: VoicemailPlan | None = None
