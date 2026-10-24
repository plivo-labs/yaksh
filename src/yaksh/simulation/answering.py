"""The recorded lines and the timings of each voicemail and call screener, and the plan that a
call plays from them."""

import wave
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from yaksh.domain.answering import (
    SCREENER_LABELS,
    VOICEMAIL_LABELS,
    AfterScreening,
    AnsweredBy,
    Answering,
    AnsweringPlan,
    MachineClip,
    MachineLine,
    Screener,
    ScreenerPlan,
    Voicemail,
    VoicemailPlan,
)
from yaksh.simulation.surroundings import SAMPLE_RATE, SOUNDS

LINES = SOUNDS / "answering.yaml"
TONE = "answering/tone.wav"
START_DELAY_S = 0.8
TONE_GAP_S = 0.3
SILENCE_END_S = 5.0
RECORDING_LIMIT_S = 120.0
ANSWER_WAIT_S = 8.0
"""The timings are estimates from the research of 2026-10-19, not measured calls."""


@dataclass(frozen=True)
class VoicemailPreset:
    greeting: str
    """The id of the line that starts it."""
    tone: bool
    full: bool = False


@dataclass(frozen=True)
class ScreenerPreset:
    prompt: str
    follow_ups: tuple[str, ...]
    acknowledgement: str
    reply: str
    hold_s: float
    limit_s: float | None = None


VOICEMAILS = {
    Voicemail.IPHONE: VoicemailPreset("iphone_greeting", tone=True),
    Voicemail.PIXEL: VoicemailPreset("pixel_greeting", tone=True),
    Voicemail.CARRIER: VoicemailPreset("carrier_greeting", tone=True),
    Voicemail.CARRIER_NO_TONE: VoicemailPreset("carrier_greeting", tone=False),
    Voicemail.MAILBOX_FULL: VoicemailPreset("mailbox_full", tone=False, full=True),
}
SCREENERS = {
    Screener.IPHONE: ScreenerPreset(
        "iphone_screen_prompt", (), "iphone_screen_ack", "iphone_screen_reply", hold_s=20
    ),
    Screener.PIXEL_CALL_ASSIST: ScreenerPreset(
        "pixel_assist_prompt", ("pixel_assist_follow_up",), "google_ack", "google_reply", hold_s=15
    ),
    Screener.GOOGLE_2018: ScreenerPreset(
        "google_2018_prompt", ("google_2018_follow_up",), "google_ack", "google_reply", hold_s=15
    ),
    Screener.SAMSUNG: ScreenerPreset(
        "samsung_prompt", (), "samsung_ack", "samsung_reply", hold_s=15
    ),
    Screener.TRUECALLER: ScreenerPreset(
        "truecaller_prompt", (), "truecaller_ack", "truecaller_reply", hold_s=10, limit_s=120
    ),
}


@cache
def line_texts() -> dict[str, str]:
    listed = yaml.safe_load(LINES.read_text())
    return {line["id"]: line["text"] for line in listed["lines"]}


def line_file(line_id: str) -> str:
    return f"answering/{line_id}.wav"


def checked(file: str) -> str:
    """The file's full path, after a check that it is in the call's format: a missing file, or
    one in another format, fails the call with a reason before it is placed."""
    path: Path = SOUNDS / file
    with wave.open(str(path)) as sound:
        if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) != (
            1,
            2,
            SAMPLE_RATE,
        ):
            raise ValueError(f"{file} is not 8 kHz 16-bit mono audio")
    return str(path)


def clip(line_id: str, line: MachineLine) -> MachineClip:
    return MachineClip(line=line, file=checked(line_file(line_id)), text=line_texts()[line_id])


def voicemail_plan(answering: Answering) -> VoicemailPlan:
    preset = VOICEMAILS[answering.voicemail]
    own = None if preset.full else answering.greeting
    line = MachineLine.MAILBOX_FULL if preset.full else MachineLine.GREETING
    return VoicemailPlan(
        label=VOICEMAIL_LABELS[answering.voicemail],
        greeting=None if own else clip(preset.greeting, line),
        own_greeting=own,
        tone=checked(TONE) if preset.tone else None,
        full=preset.full,
        tone_gap_s=TONE_GAP_S,
        silence_end_s=SILENCE_END_S,
        recording_limit_s=RECORDING_LIMIT_S,
    )


def screener_plan(answering: Answering) -> ScreenerPlan:
    preset = SCREENERS[answering.screener]
    return ScreenerPlan(
        label=SCREENER_LABELS[answering.screener],
        prompt=clip(preset.prompt, MachineLine.SCREENER),
        follow_ups=[clip(line_id, MachineLine.SCREENER) for line_id in preset.follow_ups],
        acknowledgement=clip(preset.acknowledgement, MachineLine.SCREENER),
        reply=clip(preset.reply, MachineLine.REPLY),
        hold_s=preset.hold_s,
        answer_wait_s=ANSWER_WAIT_S,
        limit_s=preset.limit_s,
        after=answering.after_screening,
    )


def answering_plan(answered_by: AnsweredBy, answering: Answering) -> AnsweringPlan | None:
    """What the persona's phone plays; None when the persona answers."""
    match answered_by:
        case AnsweredBy.CALLER:
            return None
        case AnsweredBy.VOICEMAIL:
            return AnsweringPlan(start_delay_s=START_DELAY_S, voicemail=voicemail_plan(answering))
        case AnsweredBy.SCREENER:
            passes_on = answering.after_screening is AfterScreening.VOICEMAIL
            return AnsweringPlan(
                start_delay_s=START_DELAY_S,
                screener=screener_plan(answering),
                voicemail=voicemail_plan(answering) if passes_on else None,
            )
