"""Build the background speaker clips listed in src/yaksh/simulation/sounds/speakers.yaml.

ElevenLabs (eleven_v3) speaks each line on its own; the lines are joined with the clip's pauses,
a light room effect is added, and the clip is written as 8 kHz 16-bit mono WAV with its active
speech at -20 dBFS, the caller's speech level. The script then writes each clip's length and
line start times back to speakers.yaml. Spoken lines are kept in a cache folder, so a second
run only asks ElevenLabs for new or changed lines.

    ELEVENLABS_API_KEY=... uv run python scripts/make_speaker_clips.py [CACHE_DIR]

Needs ffmpeg and ffprobe.
"""

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import urllib.request
import wave
from array import array
from pathlib import Path
from typing import Any

import yaml

SOUNDS = Path(__file__).resolve().parent.parent / "src" / "yaksh" / "simulation" / "sounds"
LIST = SOUNDS / "speakers.yaml"
HEADER = (
    "# Background speaker clips: 8 kHz 16-bit mono WAV, active speech at -20 dBFS.\n"
    "# scripts/make_speaker_clips.py builds each file from its lines and fills in seconds and"
    " start_s.\n"
)
MODEL = "eleven_v3"
RATE = 8000
CHUNK = 160
SPEECH_DBFS = -20.0
PEAK_DBFS = -3.0
EFFECT = "highpass=f=100,lowpass=f=3600,aecho=0.9:0.9:30:0.12"


def speak(text: str, voice: str, cache: Path) -> Path:
    key = hashlib.sha256(f"{MODEL}|{voice}|{text}".encode()).hexdigest()[:16]
    path = cache / f"{key}.mp3"
    if not path.exists():
        request = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
            data=json.dumps({"text": text, "model_id": MODEL}).encode(),
            headers={
                "xi-api-key": os.environ["ELEVENLABS_API_KEY"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    return path


def seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout)


def join(parts: list[Path], pauses: list[float], out: Path) -> None:
    inputs: list[str] = []
    labels = ""
    count = 0
    for index, part in enumerate(parts):
        inputs += ["-i", str(part)]
        labels += f"[{count}:a]"
        count += 1
        if index < len(pauses):
            inputs += ["-f", "lavfi", "-t", str(pauses[index]), "-i", "anullsrc=r=44100:cl=mono"]
            labels += f"[{count}:a]"
            count += 1
    graph = (
        f"{labels}concat=n={count}:v=0:a=1,aformat=sample_rates=44100:channel_layouts=mono,{EFFECT}"
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph,
         "-ar", str(RATE), "-ac", "1", "-sample_fmt", "s16", str(out)],
        check=True,
    )  # fmt: skip


def speech_dbfs(samples: array[int]) -> float:
    """The RMS of the 20 ms chunks within 30 dB of the loudest one: the speech, not the
    pauses."""
    powers = [
        sum(s * s for s in samples[at : at + CHUNK]) / CHUNK
        for at in range(0, len(samples) - CHUNK + 1, CHUNK)
    ]
    active = [p for p in powers if p > max(powers) / 1000]
    return 20 * math.log10(math.sqrt(sum(active) / len(active)) / 32768)


def level(raw: Path, out: Path) -> float:
    with wave.open(str(raw)) as file:
        samples = array("h", file.readframes(file.getnframes()))
    gain = 10 ** ((SPEECH_DBFS - speech_dbfs(samples)) / 20)
    limit = 10 ** (PEAK_DBFS / 20) * 32767
    leveled = array("h", (int(max(-limit, min(limit, s * gain))) for s in samples))
    leveled.extend([0] * (-len(leveled) % CHUNK))
    with wave.open(str(out), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(leveled.tobytes())
    return len(leveled) / RATE


def build(clip: dict[str, Any], voice: str, cache: Path) -> None:
    texts = [line["text"] for line in clip["lines"]]
    parts = [speak(text, voice, cache) for text in texts]
    starts, at = [], 0.0
    for index, part in enumerate(parts):
        starts.append(round(at, 2))
        at += seconds(part) + (clip["pauses"][index] if index < len(clip["pauses"]) else 0)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.wav"
        join(parts, clip["pauses"], raw)
        clip["seconds"] = round(level(raw, SOUNDS / "speakers" / f"{clip['id']}.wav"), 2)
    clip["lines"] = [{"start_s": s, "text": t} for s, t in zip(starts, texts, strict=True)]


def main() -> None:
    cache = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()) / "speaker-lines"
    cache.mkdir(parents=True, exist_ok=True)
    spec = yaml.safe_load(LIST.read_text())
    for clip in spec["clips"]:
        build(clip, spec["voices"][clip["voice"]], cache)
        print(f"{clip['id']}: {clip['seconds']} s")
    LIST.write_text(HEADER + yaml.safe_dump(spec, allow_unicode=True, sort_keys=False, width=100))


if __name__ == "__main__":
    main()
