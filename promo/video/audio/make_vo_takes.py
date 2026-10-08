"""Build the voiceover and timeline from recorded takes instead of synthesising them.

The short cut (v3) uses the narrator of v1 (Microsoft "Andrew", recorded with edge-tts before the
voice service was blocked here). Its takes and word timings live in audio/takes-v1/. For each scene:
optionally keep only the words from `fromWord` on, shorten pauses between words to MAX_GAP, slow the
take down with rubberband (pitch kept), and place it on the 1 s cut grid like make_vo.py does.

Reads  src/data/script.json (scene order, voAt, tail, minimum seconds; caption phrases)
       audio/takes-v1/NN-<scene>.mp3 + audio/takes-v1/timeline.v1.json (word timings)
Writes public/audio/vo/en/NN-<scene>.wav and src/data/timeline.en.json

Usage: python audio/make_vo_takes.py
"""
import json, math, subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TAKES = ROOT / "audio/takes-v1"
SCRIPT = json.loads((ROOT / "src/data/script.json").read_text(encoding="utf-8"))
FPS = SCRIPT["fps"]
BEAT_S = 60 / SCRIPT["bpm"]
Q_F = round(SCRIPT["quantumBeats"] * BEAT_S * FPS)
SR = 48_000
TEMPO = 0.94  # 6% slower than the v1 delivery: calmer and clearer, same voice and pitch
MAX_GAP = 0.30  # seconds; longer pauses between words inside a line are shortened to this
EDGE = 0.012  # seconds of fade at every cut so splices don't click

V1 = {s["id"]: s for s in json.loads((TAKES / "timeline.v1.json").read_text())["scenes"]}
FILES = {p.stem.split("-", 1)[1]: p for p in TAKES.glob("*.mp3")}


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


# Slow-down method. "atempo" (WSOLA) keeps a speaking voice more natural than rubberband, which
# left a phasey, robotic edge on these takes. POLISH warms the TTS voice a little (body, softer
# highs) and adds a very small room so it sits like a voice recorded in a space, not a dry synth.
STRETCH = "atempo"
POLISH = "equalizer=f=170:t=q:w=1:g=2.5,equalizer=f=3200:t=q:w=1.4:g=-1.5,highshelf=f=9000:g=-2,aecho=0.9:0.5:18|31:0.10|0.06"


def stretch(x: np.ndarray) -> np.ndarray:
    slow = f"atempo={TEMPO}" if STRETCH == "atempo" else f"rubberband=tempo={TEMPO}:pitch=1:transients=smooth:formant=preserved"
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                          "-af", ",".join(f for f in (slow, POLISH) if f),
                          "-f", "f32le", "-"], input=x.tobytes(), check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def fade(x: np.ndarray) -> np.ndarray:
    n = min(int(EDGE * SR), len(x) // 2)
    if n:
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def build(scene_id: str, from_word: str | None):
    """Return (samples, words) with word times in seconds from the start of the returned audio."""
    v = V1[scene_id]["vo"]
    audio = decode(FILES[scene_id])
    words = [{"text": w["text"], "start": (w["start"] - v["at"]) / FPS, "end": (w["end"] - v["at"]) / FPS} for w in v["words"]]
    if from_word:
        words = words[[w["text"] for w in words].index(from_word, 1 if from_word == "All" else 0):]
    # Keep each word plus a short margin; between words keep at most MAX_GAP of the original pause.
    pieces, out_words, t = [], [], 0.0
    lead = 0.06
    for i, w in enumerate(words):
        a = max(0.0, w["start"] - (lead if i == 0 else 0))
        nxt = words[i + 1]["start"] if i + 1 < len(words) else min(len(audio) / SR, w["end"] + 0.25)
        gap = nxt - w["end"]
        b = w["end"] + (gap if gap <= MAX_GAP else MAX_GAP / 2)
        seg_start = a
        if i > 0 and words[i - 1]["end"] + MAX_GAP < w["start"]:
            seg_start = w["start"] - MAX_GAP / 2  # the cut pause resumes just before this word
        elif i > 0:
            seg_start = prev_b
        seg = audio[int(seg_start * SR):int(b * SR)].copy()
        out_words.append({"text": w["text"], "start": t + (w["start"] - seg_start), "end": t + (w["end"] - seg_start)})
        pieces.append(fade(seg) if (i == 0 or seg_start != prev_b) else seg)
        t += len(seg) / SR
        prev_b = b
    x = stretch(np.concatenate(pieces))
    for w in out_words:
        w["start"] /= TEMPO
        w["end"] /= TEMPO
    return x, out_words


def write_wav(path: Path, x: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-c:a", "pcm_s16le", str(path)],
                   input=x.astype(np.float32).tobytes(), check=True)


def main():
    lines = SCRIPT["langs"]["en"]["lines"]
    take_cfg = SCRIPT["langs"]["en"].get("takes", {})
    scenes, cursor = [], 0
    for n, sc in enumerate(SCRIPT["scenes"], 1):
        sid = sc["id"]
        x, words = build(sid, take_cfg.get(sid, {}).get("fromWord"))
        speech_end = words[-1]["end"]
        need = sc["voAt"] + speech_end + sc["tail"]
        steps = max(round(sc["seconds"] * FPS / Q_F), math.ceil(need * FPS / Q_F - 1e-6))
        at = cursor + round(sc["voAt"] * FPS)
        rel = f"audio/vo/en/{n:02d}-{sid}.wav"
        write_wav(ROOT / "public" / rel, x)
        text = " ".join(p["text"] if isinstance(p, dict) else p for p in lines[sid]) if isinstance(lines[sid], list) else lines[sid]
        scenes.append({"id": sid, "start": cursor, "duration": steps * Q_F, "vo": {
            "file": rel, "text": text, "at": at, "durationInFrames": math.ceil(len(x) / SR * FPS),
            "speechEnd": at + round(speech_end * FPS),
            "words": [{"text": w["text"], "start": at + round(w["start"] * FPS), "end": at + round(w["end"] * FPS)} for w in words]}})
        print(f"en {sid:<10} {steps * Q_F / FPS:4.1f}s  voice {sc['voAt']:.2f}+{speech_end:.2f}s  {text}")
        cursor += steps * Q_F
    timeline = {"lang": "en", "fps": FPS, "bpm": SCRIPT["bpm"], "barFrames": round(4 * BEAT_S * FPS), "beatFrames": round(BEAT_S * FPS),
                "overlapFrames": SCRIPT["overlapFrames"], "durationInFrames": cursor, "scenes": scenes}
    (ROOT / "src/data/timeline.en.json").write_text(json.dumps(timeline, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"en: total {cursor / FPS:.1f}s ({cursor} frames)")


if __name__ == "__main__":
    main()
