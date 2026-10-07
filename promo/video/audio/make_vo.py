"""Generate the voiceover (Microsoft neural voices via edge-tts) and the timeline.

Reads  src/data/script.json
Writes public/audio/vo/<lang>/<nn>-<scene>.mp3
       src/data/timeline.<lang>.json   (absolute frame numbers for scenes, lines and words)

Scene length = the planned seconds, stretched in steps of `quantumBeats` if the line
needs more room, so every cut lands on the music's beat grid (120 BPM -> 1 beat = 0.5 s).
Usage: python audio/make_vo.py [lang ...]   (default: every language in script.json)
       python audio/make_vo.py --only <scene> [lang]
         re-voice ONE line and update just that scene in the existing timeline (every
         other scene keeps its voice and frames, so footage synced to them stays valid);
         fails if the new line no longer fits the scene's length.
"""
import asyncio, json, math, os, sys
from pathlib import Path

import edge_tts

# Behind a TLS-inspecting proxy, trust its CA (edge-tts otherwise trusts certifi only).
if os.environ.get("SSL_CERT_FILE"):
    import ssl
    import edge_tts.communicate

    edge_tts.communicate._SSL_CTX = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = json.loads((ROOT / "src/data/script.json").read_text(encoding="utf-8"))
FPS = SCRIPT["fps"]
BEAT_S = 60 / SCRIPT["bpm"]
BAR_F = round(4 * BEAT_S * FPS)
Q_S = SCRIPT["quantumBeats"] * BEAT_S  # cut grid in seconds
Q_F = round(Q_S * FPS)
TICKS = 10_000_000  # edge-tts offsets are in 100 ns units
MP3_BPS = 48_000  # audio-24khz-48kbitrate-mono-mp3 is constant bit rate


async def synth(text, voice, rate, pitch, out: Path):
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            words.append({"text": chunk["text"], "start": chunk["offset"] / TICKS, "end": (chunk["offset"] + chunk["duration"]) / TICKS})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(audio))
    return len(audio) * 8 / MP3_BPS, words


async def build(lang):
    cfg = SCRIPT["langs"][lang]
    scenes = []
    cursor = 0
    for i, sc in enumerate(SCRIPT["scenes"]):
        text = cfg["lines"][sc["id"]]
        rel = f"audio/vo/{lang}/{i + 1:02d}-{sc['id']}.mp3"
        dur, words = await synth(text, cfg["voice"], cfg["rate"], cfg["pitch"], ROOT / "public" / rel)
        speech_end = words[-1]["end"] if words else dur
        need = sc["voAt"] + speech_end + sc["tail"]
        steps = max(round(sc["seconds"] / Q_S), math.ceil(need / Q_S - 1e-6))
        start = cursor
        at = start + round(sc["voAt"] * FPS)
        scenes.append({
            "id": sc["id"],
            "start": start,
            "duration": steps * Q_F,
            "vo": {
                "file": rel,
                "text": text,
                "at": at,
                "durationInFrames": math.ceil(dur * FPS),
                "speechEnd": at + round(speech_end * FPS),
                "words": [{"text": w["text"], "start": at + round(w["start"] * FPS), "end": at + round(w["end"] * FPS)} for w in words],
            },
        })
        cursor += steps * Q_F
        print(f"{lang} {sc['id']:<10} {steps * Q_S:4.1f}s  voice {sc['voAt']:.2f}+{speech_end:.2f}s  {text}")
    timeline = {
        "lang": lang,
        "fps": FPS,
        "bpm": SCRIPT["bpm"],
        "barFrames": BAR_F,
        "beatFrames": round(BEAT_S * FPS),
        "overlapFrames": SCRIPT["overlapFrames"],
        "durationInFrames": cursor,
        "scenes": scenes,
    }
    (ROOT / f"src/data/timeline.{lang}.json").write_text(json.dumps(timeline, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{lang}: total {cursor / FPS:.1f}s ({cursor} frames)")


async def only(scene_id, lang):
    cfg = SCRIPT["langs"][lang]
    path = ROOT / f"src/data/timeline.{lang}.json"
    timeline = json.loads(path.read_text(encoding="utf-8"))
    i, sc = next((i, s) for i, s in enumerate(SCRIPT["scenes"]) if s["id"] == scene_id)
    t = next(s for s in timeline["scenes"] if s["id"] == scene_id)
    text = cfg["lines"][scene_id]
    rel = f"audio/vo/{lang}/{i + 1:02d}-{scene_id}.mp3"
    tmp = ROOT / "public" / (rel + ".new")
    dur, words = await synth(text, cfg["voice"], cfg["rate"], cfg["pitch"], tmp)
    speech_end = words[-1]["end"] if words else dur
    need_f = math.ceil((sc["voAt"] + speech_end + sc["tail"]) * FPS)
    if need_f > t["duration"]:
        tmp.unlink()
        sys.exit(f"{scene_id}: the new line needs {need_f} frames but the scene has {t['duration']}; run a full build instead")
    tmp.replace(ROOT / "public" / rel)
    at = t["vo"]["at"]
    t["vo"].update({
        "text": text,
        "durationInFrames": math.ceil(dur * FPS),
        "speechEnd": at + round(speech_end * FPS),
        "words": [{"text": w["text"], "start": at + round(w["start"] * FPS), "end": at + round(w["end"] * FPS)} for w in words],
    })
    path.write_text(json.dumps(timeline, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{lang} {scene_id}: voice {sc['voAt']:.2f}+{speech_end:.2f}s in a {t['duration'] / FPS:.1f}s scene  {text}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--only"]:
        asyncio.run(only(args[1], args[2] if len(args) > 2 else "en"))
    else:
        for lang in args or list(SCRIPT["langs"]):
            asyncio.run(build(lang))
