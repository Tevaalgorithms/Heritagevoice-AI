"""Make the synthetic-voice clips for the demo library, with the Mac's built-in voices.

    uv run python scripts/make_demo_audio.py

macOS only (`say` and `afconvert`). Writes `app/demo_audio/<id>.m4a`, one clip per recording whose
language has a voice on this Mac (Malayalam has none, so that recording stays without sound). Every
segment is padded with silence to fill its time slot in `demo_recordings.json`, so the clip is as
long as the recording and the timings never change. The clips are computer-generated speech, not
people, and the site says so when one is played.
"""

import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "app" / "demo_recordings.json"
OUT = ROOT / "app" / "demo_audio"
VOICES = {
    "ta": "Vani",
    "hi": "Lekha",
    "te": "Geeta",
    "bn": "Piya",
    "fr": "Thomas",
    "es": "Mónica",
    "pt": "Joana",
    "en": "Samantha",
}
RATE = 150  # words per minute to start with; faster only when a sentence does not fit its slot
RATE_STEP, MAX_TRIES, SLACK_S = 20, 5, 0.3
SAMPLE_RATE = 22050


def run(*command: str) -> None:
    subprocess.run(command, check=True, capture_output=True)


def speak(voice: str, text: str, slot_s: float, folder: Path) -> list[bytes]:
    """The sentence as 16-bit mono audio, spoken fast enough to fit its slot."""
    for attempt in range(MAX_TRIES):
        aiff, wav = folder / "s.aiff", folder / "s.wav"
        run("say", "-v", voice, "-r", str(RATE + attempt * RATE_STEP), "-o", str(aiff), text)
        run("afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1", str(aiff), str(wav))
        with wave.open(str(wav)) as clip:
            frames = clip.readframes(clip.getnframes())
        if len(frames) / 2 / SAMPLE_RATE <= slot_s - SLACK_S:
            return [frames]
    raise SystemExit(f"This sentence does not fit {slot_s}s even when spoken fast: {text}")


def clip_for(recording: dict, voice: str, folder: Path) -> Path:
    """One recording: each segment spoken, then silence up to the end of its slot."""
    pieces: list[bytes] = []
    for segment in recording["segments"]:
        slot = segment["end_s"] - segment["start_s"]
        frames = b"".join(speak(voice, segment["text"], slot, folder))
        silence = b"\0\0" * (round(slot * SAMPLE_RATE) - len(frames) // 2)
        pieces += [frames, silence]
    whole, m4a = folder / "whole.wav", OUT / f"{recording['id']}.m4a"
    with wave.open(str(whole), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(b"".join(pieces))
    run("afconvert", "-f", "m4af", "-d", "aac", "-b", "48000", str(whole), str(m4a))
    return m4a


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("This needs macOS: it uses the `say` and `afconvert` commands.")
    OUT.mkdir(exist_ok=True)
    for recording in json.loads(CORPUS.read_text(encoding="utf-8"))["recordings"]:
        voice = VOICES.get(recording["language"])
        if voice is None:
            print(f"{recording['id']}: no voice for {recording['language']}, no audio")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            path = clip_for(recording, voice, Path(tmp))
        print(f"{recording['id']}: {path.stat().st_size // 1024} KB with {voice}")


if __name__ == "__main__":
    main()
