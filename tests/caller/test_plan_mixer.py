import wave
from array import array
from pathlib import Path

from yaksha.caller.audio import FRAME_BYTES, SAMPLE_RATE, PlanMixer
from yaksha.domain.surroundings import Layer, NoiseSound, SoundPlan, SpeakerKind

TICK = FRAME_BYTES // 2  # samples in one 20 ms frame
CAFE = NoiseSound.CAFE
TV = SpeakerKind.TV


def sound(path: Path, samples: list[int]) -> str:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(SAMPLE_RATE)
        file.writeframes(array("h", samples).tobytes())
    return str(path)


async def send(mixer: PlanMixer, voice: list[int]) -> list[int]:
    """The caller's samples through the mixer, one 20 ms frame at a time, as the output does."""
    await mixer.start(SAMPLE_RATE)
    sent = array("h")
    for at in range(0, len(voice), TICK):
        sent.frombytes(await mixer.mix(array("h", voice[at : at + TICK]).tobytes()))
    return sent.tolist()


async def test_layers_sound_from_their_start_to_their_end_looped_or_once(tmp_path: Path) -> None:
    loop = sound(tmp_path / "loop.wav", [100, 200])
    once = sound(tmp_path / "once.wav", [1000] * (TICK * 2))
    mixer = PlanMixer(
        SoundPlan(
            layers=[
                Layer(
                    file=loop,
                    sound=CAFE,
                    gain=1,
                    start_s=0,
                    end_s=TICK * 3 / SAMPLE_RATE,
                    loop=True,
                ),
                Layer(file=once, speaker=TV, gain=0.5, start_s=TICK * 2 / SAMPLE_RATE, loop=False),
            ]
        )
    )

    sent = await send(mixer, [10] * (TICK * 6))

    frames = [sent[at : at + TICK] for at in range(0, len(sent), TICK)]
    assert frames[0] == frames[1] == [110, 210] * (TICK // 2)
    assert frames[2] == [610, 710] * (TICK // 2)
    assert frames[3] == [510] * TICK
    assert frames[4] == frames[5] == [10] * TICK


async def test_the_sum_is_clipped_to_16_bits(tmp_path: Path) -> None:
    loud = sound(tmp_path / "loud.wav", [30000, -30000])
    mixer = PlanMixer(
        SoundPlan(layers=[Layer(file=loud, sound=CAFE, gain=1, start_s=0, loop=True)])
    )

    sent = await send(mixer, [30000, -30000] * (TICK // 2))

    assert sent == [32767, -32768] * (TICK // 2)


async def test_a_loop_that_wraps_inside_a_frame_stops_at_its_planned_end(tmp_path: Path) -> None:
    # A 3-sample loop starting 1 sample in, cut off 5 samples in: one frame holds the start,
    # a wrap back to the first sample, and the end.
    loop = sound(tmp_path / "loop.wav", [1, 2, 3])
    plan = SoundPlan(
        layers=[
            Layer(
                file=loop,
                sound=CAFE,
                gain=1,
                start_s=1 / SAMPLE_RATE,
                end_s=5 / SAMPLE_RATE,
                loop=True,
            )
        ]
    )

    sent = await send(PlanMixer(plan), [0] * TICK)

    assert sent[:7] == [0, 1, 2, 3, 1, 0, 0]
    assert set(sent[7:]) == {0}
