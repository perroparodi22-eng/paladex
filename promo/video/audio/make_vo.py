"""Generate the voiceover (Microsoft neural voices via edge-tts) and the timeline.

Reads  src/data/script.json
Writes public/audio/vo/<lang>/<nn>-<scene>.wav
       src/data/timeline.<lang>.json   (absolute frame numbers for scenes, lines and words)

Two engines: Microsoft neural voices through edge-tts (voice like "en-US-AndrewMultilingualNeural",
needs speech.platform.bing.com), or Kokoro, an open model that runs locally (voice like
"kokoro:am_michael"; weights downloaded once from GitHub into audio/models/, git-ignored).

A line is a list of phrases, each voiced separately with its own rate / pitch / volume and
followed by `gap` seconds of silence, so the delivery can change tone from phrase to phrase
(edge-tts takes no SSML styles). A plain string is one phrase.

Scene length = the planned seconds, stretched in steps of `quantumBeats` if the line
needs more room, so every cut lands on the music's beat grid (120 BPM -> 1 beat = 0.5 s).

Usage: python audio/make_vo.py [lang ...]          (default: every language in script.json)
       python audio/make_vo.py --estimate [lang]    no network: estimated word timings and
         silent voice files, so scenes can be built before the real voice exists. Every scene
         derives its frames from the word timings, so it re-syncs when the voice is generated.
       python audio/make_vo.py --only <scene> [lang]
         re-voice ONE line and update just that scene in the existing timeline (every other
         scene keeps its voice and frames); fails if the line no longer fits the scene.
       python audio/make_vo.py --audition <voice>[,<voice>...]
         a short sample of a few lines per voice in out/voices/<voice>.wav, to pick a voice.
"""
import asyncio, io, json, math, os, re, subprocess, sys, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = json.loads((ROOT / "src/data/script.json").read_text(encoding="utf-8"))
FPS = SCRIPT["fps"]
BEAT_S = 60 / SCRIPT["bpm"]
BAR_F = round(4 * BEAT_S * FPS)
Q_S = SCRIPT["quantumBeats"] * BEAT_S  # cut grid in seconds
Q_F = round(Q_S * FPS)
TICKS = 10_000_000  # edge-tts offsets are in 100 ns units
SR = 24_000  # edge-tts voices are 24 kHz mono


def edge():
    import edge_tts

    # Behind a TLS-inspecting proxy, trust its CA (edge-tts otherwise trusts certifi only).
    if os.environ.get("SSL_CERT_FILE"):
        import ssl
        import edge_tts.communicate

        edge_tts.communicate._SSL_CTX = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    return edge_tts


def phrases(line, cfg):
    base = {"rate": cfg.get("rate", "+0%"), "pitch": cfg.get("pitch", "+0Hz"), "volume": "+0%", "gap": 0.0}
    if isinstance(line, str):
        return [{**base, "text": line}]
    return [{**base, **p} for p in line]


def line_text(line):
    return " ".join(p["text"] for p in phrases(line, {}))


def pcm(mp3: bytes) -> bytes:
    """Decode edge-tts MP3 to 16-bit mono PCM at SR."""
    return subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(SR), "pipe:1"],
        input=mp3, capture_output=True, check=True,
    ).stdout


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * round(seconds * SR)


KOKORO = None
KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def kokoro():
    global KOKORO
    if KOKORO is None:
        from kokoro_onnx import Kokoro

        d = ROOT / "audio" / "models"
        d.mkdir(parents=True, exist_ok=True)
        for name, url in KOKORO_FILES.items():
            if not (d / name).exists():
                print(f"downloading {name}")
                subprocess.run(["curl", "-sS", "-L", "-o", str(d / name), url], check=True)
        KOKORO = Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
    return KOKORO


def pct(v: str) -> float:
    m = re.match(r"([+-]?\d+(?:\.\d+)?)%", v or "")
    return float(m.group(1)) / 100 if m else 0.0


def synth_kokoro(p, voice):
    """Kokoro has no pitch/volume controls and no word timings: speed from `rate`, pitch shifted
    with rubberband (Hz offsets relative to a ~110 Hz male voice), gain from `volume`; word timings
    spread over the detected speech by syllable weight (each phrase is voiced on its own, so the
    phrase boundaries, where the key sync points are, are exact)."""
    import numpy as np

    speed = min(2.0, max(0.5, 1 + pct(p["rate"])))
    y, sr = kokoro().create(p["text"], voice=voice, speed=speed, lang="en-us")
    y = np.asarray(y, dtype=np.float32)
    if sr != SR:
        raise SystemExit(f"kokoro sample rate {sr} != {SR}")
    m = re.match(r"([+-]?\d+(?:\.\d+)?)Hz", p["pitch"] or "")
    ratio = (110 + float(m.group(1))) / 110 if m else 1.0
    if abs(ratio - 1) > 1e-3:
        y = np.frombuffer(
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
                 "-af", f"rubberband=pitch={ratio:.5f}:formant=preserved", "-f", "f32le", "pipe:1"],
                input=y.tobytes(), capture_output=True, check=True,
            ).stdout, dtype=np.float32)
    y = y * (1 + pct(p["volume"]))
    # Trim to the speech (keep 40 ms either side) and find where it starts/ends.
    env = np.convolve(np.abs(y), np.ones(240) / 240, mode="same")
    on = np.flatnonzero(env > 0.02 * env.max()) if len(y) else np.array([0])
    a, b = max(0, on[0] - 960), min(len(y), on[-1] + 960)
    y = y[a:b]
    s0, s1 = (on[0] - a) / SR, (on[-1] - a) / SR
    words = [w for w in p["text"].split()]
    weight = [max(1, len(re.findall(r"[aeiouy]+", re.sub(r"[^a-z]", "", w.lower())))) + 0.3 for w in words]
    gaps = [0.12 if re.search(r"[.?!,]$", w) else 0.0 for w in words]
    span = max(0.05, s1 - s0 - sum(gaps[:-1]))
    t = s0
    out = []
    for w, k, g in zip(words, weight, gaps):
        d = span * k / sum(weight)
        out.append({"text": re.sub(r"[^\w'-]", "", w), "start": t, "end": t + d})
        t += d + g
    raw = (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()
    return raw, len(y) / SR, out


async def synth(p, voice):
    if voice.startswith("kokoro:"):
        return synth_kokoro(p, voice.split(":", 1)[1])
    com = edge().Communicate(p["text"], voice, rate=p["rate"], pitch=p["pitch"], volume=p["volume"], boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            words.append({"text": chunk["text"], "start": chunk["offset"] / TICKS, "end": (chunk["offset"] + chunk["duration"]) / TICKS})
    raw = pcm(bytes(audio))
    return raw, len(raw) / 2 / SR, words


def estimate(p):
    """Rough timings for a phrase without the voice service (about 3 words/s at +0%)."""
    m = re.match(r"([+-]\d+)%", p["rate"])
    speed = 1 + (int(m.group(1)) if m else 0) / 100
    t = 0.08
    words = []
    for w in p["text"].split():
        core = re.sub(r"[^\w'-]", "", w)
        dur = (0.11 + 0.052 * len(core)) / speed
        words.append({"text": core, "start": t, "end": t + dur})
        t += dur + (0.16 if re.search(r"[.?!]$", w) else 0.1 if w.endswith(",") else 0.02) / speed
    t += 0.08
    return silence(t), t, words


async def voice_line(line, cfg, voice, est):
    """Voice every phrase of a line and stitch them. Returns (pcm, seconds, words, speech_end)."""
    out = bytearray()
    words = []
    ps = phrases(line, cfg)
    for k, p in enumerate(ps):
        raw, dur, ws = estimate(p) if est else await synth(p, voice)
        t0 = len(out) / 2 / SR
        words += [{"text": w["text"], "start": t0 + w["start"], "end": t0 + w["end"]} for w in ws]
        out += raw
        if k < len(ps) - 1:
            out += silence(p["gap"])
    dur = len(out) / 2 / SR
    return bytes(out), dur, words, (words[-1]["end"] if words else dur)


def write_wav(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(raw)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(buf.getvalue())
    tmp.replace(path)


def vo_entry(rel, text, at, dur, speech_end, words):
    return {
        "file": rel,
        "text": text,
        "at": at,
        "durationInFrames": math.ceil(dur * FPS),
        "speechEnd": at + round(speech_end * FPS),
        "words": [{"text": w["text"], "start": at + round(w["start"] * FPS), "end": at + round(w["end"] * FPS)} for w in words],
    }


async def build(lang, est=False):
    cfg = SCRIPT["langs"][lang]
    scenes = []
    cursor = 0
    for i, sc in enumerate(SCRIPT["scenes"]):
        line = cfg["lines"][sc["id"]]
        rel = f"audio/vo/{lang}/{i + 1:02d}-{sc['id']}.wav"
        raw, dur, words, speech_end = await voice_line(line, cfg, cfg["voice"], est)
        write_wav(ROOT / "public" / rel, raw)
        need = sc["voAt"] + speech_end + sc["tail"]
        steps = max(round(sc["seconds"] / Q_S), math.ceil(need / Q_S - 1e-6))
        start = cursor
        at = start + round(sc["voAt"] * FPS)
        scenes.append({"id": sc["id"], "start": start, "duration": steps * Q_F, "vo": vo_entry(rel, line_text(line), at, dur, speech_end, words)})
        cursor += steps * Q_F
        print(f"{lang} {sc['id']:<10} {steps * Q_S:4.1f}s  voice {sc['voAt']:.2f}+{speech_end:.2f}s  {line_text(line)}")
    timeline = {
        "lang": lang,
        "fps": FPS,
        "bpm": SCRIPT["bpm"],
        "barFrames": BAR_F,
        "beatFrames": round(BEAT_S * FPS),
        "overlapFrames": SCRIPT["overlapFrames"],
        "durationInFrames": cursor,
        **({"estimated": True} if est else {}),
        "scenes": scenes,
    }
    (ROOT / f"src/data/timeline.{lang}.json").write_text(json.dumps(timeline, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{lang}: total {cursor / FPS:.1f}s ({cursor} frames){'  [ESTIMATED timings, silent voice]' if est else ''}")


async def only(scene_id, lang):
    cfg = SCRIPT["langs"][lang]
    path = ROOT / f"src/data/timeline.{lang}.json"
    timeline = json.loads(path.read_text(encoding="utf-8"))
    i, sc = next((i, s) for i, s in enumerate(SCRIPT["scenes"]) if s["id"] == scene_id)
    t = next(s for s in timeline["scenes"] if s["id"] == scene_id)
    line = cfg["lines"][scene_id]
    raw, dur, words, speech_end = await voice_line(line, cfg, cfg["voice"], False)
    need_f = math.ceil((sc["voAt"] + speech_end + sc["tail"]) * FPS)
    if need_f > t["duration"]:
        sys.exit(f"{scene_id}: the new line needs {need_f} frames but the scene has {t['duration']}; run a full build instead")
    rel = f"audio/vo/{lang}/{i + 1:02d}-{scene_id}.wav"
    write_wav(ROOT / "public" / rel, raw)
    t["vo"] = vo_entry(rel, line_text(line), t["vo"]["at"], dur, speech_end, words)
    path.write_text(json.dumps(timeline, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{lang} {scene_id}: voice {sc['voAt']:.2f}+{speech_end:.2f}s in a {t['duration'] / FPS:.1f}s scene  {line_text(line)}")


async def audition(voices, lang="en"):
    cfg = SCRIPT["langs"][lang]
    for voice in voices:
        out = bytearray()
        print(f"audition {voice}")
        for sid in ("cold-open", "problem", "reveal", "turn"):
            raw, *_ = await voice_line(cfg["lines"][sid], cfg, voice, False)
            out += raw + silence(0.6)
        path = ROOT / "out" / "voices" / f"{voice.replace(':', '-')}.wav"
        write_wav(path, bytes(out))
        print(f"audition -> {path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--only"]:
        asyncio.run(only(args[1], args[2] if len(args) > 2 else "en"))
    elif args[:1] == ["--audition"]:
        asyncio.run(audition(args[1].split(",")))
    elif args[:1] == ["--estimate"]:
        asyncio.run(build(args[1] if len(args) > 1 else "en", est=True))
    else:
        for lang in args or list(SCRIPT["langs"]):
            asyncio.run(build(lang))
