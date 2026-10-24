"""The persona's phone on a call that its voicemail or call screener answers: what it plays,
when it listens, and how it ends the call or hands it to the persona."""

import asyncio
import io
import logging
import wave
from collections.abc import Callable
from pathlib import Path

from pipecat.frames.frames import LLMMessagesAppendFrame

from yaksh.caller.audio import Clock, bytes_ms, read_pcm
from yaksh.caller.pipeline import CallerKeys, CallState, Persona
from yaksh.caller.transcript import TranscriptBuilder
from yaksh.diagnostics import describe_exception
from yaksh.domain.answering import (
    AfterScreening,
    AnsweringPlan,
    MachineClip,
    MachineLine,
    ScreenerPlan,
    VoicemailPlan,
)
from yaksh.domain.conversations import (
    CallObserver,
    CallRequest,
    EndReason,
    WireEvent,
    WireEventKind,
)
from yaksh.integrations.elevenlabs import ElevenLabsClient

log = logging.getLogger(__name__)

POLL_S = 0.1
PLAY_SLACK_S = 3.0
"""How much longer than its audio a line may take to be reported played."""
ANSWER_CAP_S = 30.0
"""How long the screener waits at most for an agent that is still speaking."""
HANDOVER_NOTE = (
    "Your phone's call screener answered this call first and asked the agent who it is and why "
    "it calls. The agent's answers to the screener are above. You have read them, and you pick "
    "up the call now."
)


def own_greeting(request: CallRequest, keys: CallerKeys) -> asyncio.Future[bytes] | None:
    """Start speaking the persona's own voicemail greeting, so it is ready when the call
    connects; None when the call plays no own greeting."""
    plan = request.answering
    text = plan.voicemail.own_greeting if plan and plan.voicemail else None
    if text is None:
        return None
    return asyncio.ensure_future(spoken(keys.elevenlabs, request, text))


async def spoken(key: str, request: CallRequest, text: str) -> bytes:
    audio = await ElevenLabsClient(key).speak(request.voice, request.caller_language, text)
    if audio is None:
        raise ValueError("ElevenLabs no longer has the persona's voice")
    with wave.open(io.BytesIO(audio)) as file:
        return file.readframes(file.getnframes())


class AnsweringScript:
    """Plays the persona's phone from the moment the call connects: a call screener, a
    voicemail, or a screener that passes the call on to the voicemail or to the persona. A
    machine ends the call with the reason that it gives, as a person who hangs up would."""

    def __init__(
        self,
        plan: AnsweringPlan,
        persona: Persona,
        state: CallState,
        transcript: TranscriptBuilder,
        observer: CallObserver,
        clock: Clock,
        greeting: asyncio.Future[bytes] | None,
    ) -> None:
        assert persona.player is not None and persona.gate is not None
        self._plan = plan
        self._persona = persona
        self._player = persona.player
        self._gate = persona.gate
        self._state = state
        self._transcript = transcript
        self._observer = observer
        self._clock = clock
        self._greeting = greeting

    async def run(self) -> None:
        try:
            await asyncio.sleep(self._plan.start_delay_s)
            if self._plan.screener is not None and await self._screen(self._plan.screener):
                return
            if self._plan.voicemail is not None:
                await self._voicemail(self._plan.voicemail)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.exception("the persona's phone failed")
            self._state.blame(f"the persona's phone failed: {describe_exception(error)}")
            self._state.end(EndReason.ERROR)

    async def _screen(self, plan: ScreenerPlan) -> bool:
        """True when the screener ended the call or the persona picked up."""
        try:
            async with asyncio.timeout(plan.limit_s):
                for question in (plan.prompt, *plan.follow_ups):
                    asked = self._transcript.agent_turns
                    await self._play_clip(question)
                    if not await self._answer(asked, plan.answer_wait_s):
                        self._end(
                            EndReason.SCREENER_ENDED, "The agent did not answer the screener."
                        )
                        return True
                await self._play_clip(plan.acknowledgement)
                self._mark(WireEventKind.HOLD_STARTED, str(round(plan.hold_s * 1000)))
                await asyncio.sleep(plan.hold_s)
        except TimeoutError:
            self._end(
                EndReason.SCREENER_ENDED,
                f"The screener ended the call at its {plan.limit_s:g} s limit.",
            )
            return True
        match plan.after:
            case AfterScreening.PICKS_UP:
                await self._hand_over()
                return True
            case AfterScreening.VOICEMAIL:
                return False
            case AfterScreening.REPLY:
                await self._play_clip(plan.reply)
                self._end(EndReason.SCREENER_ENDED, "The screener sent a reply.")
                return True
            case AfterScreening.DECLINES:
                self._end(EndReason.SCREENER_ENDED, "The screener declined the call.")
                return True

    async def _answer(self, asked: int, wait_s: float) -> bool:
        """Whether the agent ends a turn after `asked`, its turn count when the question started,
        within wait_s of the question's end: an answer over the question counts, and an agent
        still speaking at wait_s gets until its turn ends."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_s
        cap = loop.time() + ANSWER_CAP_S
        while self._transcript.agent_turns == asked:
            now = loop.time()
            speaking = self._transcript.agent_speaking or self._transcript.agent_voice
            if now >= cap or (now >= deadline and not speaking):
                return False
            await asyncio.sleep(POLL_S)
        return True

    async def _hand_over(self) -> None:
        """The persona picks up: it reads what the agent told the screener, says its first
        words as at any pickup, and answers from the agent's next turn."""
        self._mark(WireEventKind.HANDOVER)
        self._gate.open()
        await self._persona.worker.queue_frame(
            LLMMessagesAppendFrame(
                messages=[{"role": "system", "content": HANDOVER_NOTE}], run_llm=False
            )
        )
        await self._persona.speak_first()

    async def _voicemail(self, plan: VoicemailPlan) -> None:
        if plan.greeting is not None:
            await self._play_clip(plan.greeting)
        else:
            assert self._greeting is not None and plan.own_greeting is not None
            await self._play(await self._greeting, plan.own_greeting, MachineLine.GREETING)
        if plan.full:
            self._end(EndReason.VOICEMAIL_ENDED, "The mailbox is full.")
            return
        if plan.tone is not None:
            await asyncio.sleep(plan.tone_gap_s)
            await self._tone(Path(plan.tone))
        await self._record(plan)

    async def _record(self, plan: VoicemailPlan) -> None:
        """Record until the agent has been silent for the silence end, or the limit passes."""
        started = self._clock.ms()
        silence_ms = round(plan.silence_end_s * 1000)
        while True:
            now = self._clock.ms()
            if now - started >= plan.recording_limit_s * 1000:
                self._end(
                    EndReason.VOICEMAIL_ENDED,
                    f"The voicemail stopped recording at its {plan.recording_limit_s:g} s limit.",
                )
                return
            heard = max(started, self._transcript.agent_voice_ended_ms or started)
            if not self._transcript.agent_voice and now - heard >= silence_ms:
                self._end(
                    EndReason.VOICEMAIL_ENDED,
                    f"The voicemail stopped recording after {plan.silence_end_s:g} s of silence.",
                )
                return
            await asyncio.sleep(POLL_S)

    async def _play_clip(self, clip: MachineClip) -> None:
        await self._play(read_pcm(Path(clip.file)), clip.text, clip.line)

    async def _play(self, pcm: bytes, text: str, line: MachineLine) -> None:
        """Play a line and return once Plivo reports it played."""
        self._transcript.machine(text, line)
        await self._player.play(pcm, text, line)
        await self._until(lambda: self._transcript.caller_quiet, bytes_ms(len(pcm)) / 1000)

    async def _tone(self, file: Path) -> None:
        pcm = read_pcm(file)
        seconds = bytes_ms(len(pcm)) / 1000
        self._mark(WireEventKind.CALLER_SOUND, f"tone, {seconds:g} s")
        await self._player.play(pcm, None, MachineLine.TONE)
        await asyncio.sleep(seconds)
        await self._until(lambda: self._transcript.caller_quiet, 0)

    async def _until(self, done: Callable[[], bool], audio_s: float) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + audio_s + PLAY_SLACK_S
        while not done() and loop.time() < deadline:
            await asyncio.sleep(POLL_S)

    def _end(self, reason: EndReason, why: str) -> None:
        if self._state.end(reason):
            self._state.caller_reason = why

    def _mark(self, kind: WireEventKind, detail: str | None = None) -> None:
        self._observer.wire_event(WireEvent(kind=kind, at_ms=self._clock.ms(), detail=detail))
