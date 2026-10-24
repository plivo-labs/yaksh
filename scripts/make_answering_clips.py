"""Build the voicemail and call screener lines listed in src/yaksh/simulation/sounds/answering.yaml.

ElevenLabs speaks each line in its phone system's voice, at the call's 8 kHz, as the voice
previews do. Each line is written as 16-bit mono WAV with its active speech at -20 dBFS, the
caller's speech level. The script also writes the voicemail tone: a 440 Hz sine, 1 s, with a
-6 dBFS peak. Spoken lines are kept in a cache folder, so a second run only asks ElevenLabs for
new or changed lines.

    ELEVENLABS_API_KEY=... uv run python scripts/make_answering_clips.py [CACHE_DIR]
"""

import hashlib
import json
import math
import os
import sys
import tempfile
import urllib.request
import wave
from array import array
from pathlib import Path

import yaml

SOUNDS = Path(__file__).resolve().parent.parent / "src" / "yaksh" / "simulation" / "sounds"
LIST = SOUNDS / "answering.yaml"
OUT = SOUNDS / "answering"
MODEL = "eleven_flash_v2_5"
STABILITY = 0.8
RATE = 8000
CHUNK = 160
SPEECH_DBFS = -20.0
PEAK_DBFS = -3.0
TONE_HZ = 440
TONE_S = 1.0
TONE_PEAK_DBFS = -6.0
TONE_FADE_S = 0.01


def speak(text: str, voice: str, cache: Path) -> array[int]:
    key = hashlib.sha256(f"{MODEL}|{voice}|{STABILITY}|{text}".encode()).hexdigest()[:16]
    path = cache / f"{key}.pcm"
    if not path.exists():
        request = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_8000",
            data=json.dumps(
                {"text": text, "model_id": MODEL, "voice_settings": {"stability": STABILITY}}
            ).encode(),
            headers={
                "xi-api-key": os.environ["ELEVENLABS_API_KEY"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    return array("h", path.read_bytes())


def speech_dbfs(samples: array[int]) -> float:
    """The RMS of the 20 ms chunks within 30 dB of the loudest one: the speech, not the
    pauses."""
    powers = [
        sum(s * s for s in samples[at : at + CHUNK]) / CHUNK
        for at in range(0, len(samples) - CHUNK + 1, CHUNK)
    ]
    active = [p for p in powers if p > max(powers) / 1000]
    return 20 * math.log10(math.sqrt(sum(active) / len(active)) / 32768)


def write(samples: array[int], out: Path) -> None:
    samples.extend([0] * (-len(samples) % CHUNK))
    with wave.open(str(out), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(samples.tobytes())


def leveled(samples: array[int]) -> array[int]:
    gain = 10 ** ((SPEECH_DBFS - speech_dbfs(samples)) / 20)
    limit = 10 ** (PEAK_DBFS / 20) * 32767
    return array("h", (int(max(-limit, min(limit, s * gain))) for s in samples))


def tone() -> array[int]:
    count = int(TONE_S * RATE)
    fade = int(TONE_FADE_S * RATE)
    peak = 10 ** (TONE_PEAK_DBFS / 20) * 32767
    return array(
        "h",
        (
            int(
                peak
                * min(1, n / fade, (count - n) / fade)
                * math.sin(2 * math.pi * TONE_HZ * n / RATE)
            )
            for n in range(count)
        ),
    )


def main() -> None:
    cache = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()) / "answering-lines"
    cache.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)
    spec = yaml.safe_load(LIST.read_text())
    for line in spec["lines"]:
        samples = leveled(speak(line["text"], spec["voices"][line["voice"]], cache))
        write(samples, OUT / f"{line['id']}.wav")
        print(f"{line['id']}: {len(samples) / RATE:.2f} s")
    write(tone(), OUT / "tone.wav")
    print(f"tone: {TONE_S} s")


if __name__ == "__main__":
    main()
