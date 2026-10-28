import asyncio
from collections.abc import Sequence

from tests.conftest import phone_request
from yaksh.caller.prepared import Prepared
from yaksh.domain.answering import AnsweredBy, Answering, Voicemail
from yaksh.domain.conversations import CallRequest
from yaksh.domain.scenarios import Interruption
from yaksh.simulation.answering import answering_plan


def call(greeting: str | None = None, lines: Sequence[str] = ()) -> CallRequest:
    voicemail = Answering(voicemail=Voicemail.CARRIER_NO_TONE, greeting=greeting)
    return phone_request(
        answering=answering_plan(AnsweredBy.VOICEMAIL, voicemail) if greeting else None,
        interruptions=[Interruption(say=line) for line in lines],
    )


async def test_the_lines_are_made_in_order_one_request_at_a_time() -> None:
    asked: list[str] = []
    at_once = 0

    async def speak(text: str) -> bytes:
        nonlocal at_once
        asked.append(text)
        at_once += 1
        assert at_once == 1, "one request at a time"
        await asyncio.sleep(0.01)
        at_once -= 1
        return text.encode()

    prepared = Prepared(call(lines=["Wait.", "Mm-hmm.", "Hold on."]))
    prepared.make(speak)
    made = [await line for line in prepared.lines]

    assert asked == ["Wait.", "Mm-hmm.", "Hold on."]
    assert made == [b"Wait.", b"Mm-hmm.", b"Hold on."]
    assert prepared.own is None and prepared.items == prepared.lines


async def test_the_own_greeting_is_the_first_item() -> None:
    async def speak(text: str) -> bytes:
        return text.encode()

    prepared = Prepared(call(greeting="Hi, it's Rachel."))
    prepared.make(speak)

    assert prepared.own is not None and await prepared.own == b"Hi, it's Rachel."
    assert prepared.items == (prepared.own,) and prepared.lines == ()


async def test_a_failed_speech_is_tried_once_more_and_a_second_failure_fails_only_its_line() -> (
    None
):
    failures = {"Wait.": 1, "Mm-hmm.": 2}

    async def speak(text: str) -> bytes:
        if failures.get(text, 0) > 0:
            failures[text] -= 1
            raise RuntimeError(f"no voice for {text}")
        return text.encode()

    prepared = Prepared(call(lines=["Wait.", "Mm-hmm.", "Hold on."]))
    prepared.make(speak)
    wait, backchannel, hold = await asyncio.gather(*prepared.lines, return_exceptions=True)

    assert (wait, hold) == (b"Wait.", b"Hold on.")
    assert isinstance(backchannel, RuntimeError) and str(backchannel) == "no voice for Mm-hmm."


async def test_closing_stops_the_speech_request_that_the_call_no_longer_needs() -> None:
    started, stopped = asyncio.Event(), asyncio.Event()

    async def speak(_text: str) -> bytes:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            stopped.set()
            raise
        return b""

    prepared = Prepared(call(lines=["Wait.", "Mm-hmm."]))
    prepared.make(speak)
    await started.wait()
    await prepared.close()

    assert stopped.is_set()
    assert all(item.cancelled() for item in prepared.items)


async def test_a_call_with_no_greeting_and_no_lines_makes_nothing() -> None:
    async def speak(_text: str) -> bytes:
        raise AssertionError("nothing to say")

    prepared = Prepared(call())
    prepared.make(speak)
    await prepared.close()

    assert prepared.items == ()
