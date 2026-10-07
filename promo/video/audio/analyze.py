"""Engineering checks for the music bed: stats per scene, spectrogram/waveform PNGs and a
rough voice + ducked-music mix check (out/audio/)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import signal as sps

from dsp import SR, bp, db, k_weight, lufs_integrated, nsamp, read_wav, rms_env, true_peak, write_wav

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out/audio"
FPS = 60
FRAME = SR // FPS

_STOPS = [(0.0, (4, 4, 10)), (0.25, (60, 14, 100)), (0.5, (170, 40, 90)), (0.72, (240, 110, 30)),
          (0.9, (250, 210, 80)), (1.0, (255, 255, 230))]


def _cmap(v: np.ndarray) -> np.ndarray:
    v = np.clip(v, 0, 1)
    out = np.zeros(v.shape + (3,))
    xs = [s[0] for s in _STOPS]
    for c in range(3):
        out[..., c] = np.interp(v, xs, [s[1][c] for s in _STOPS])
    return out.astype(np.uint8)


def _font(size=14):
    for f in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def spectrogram_img(x: np.ndarray, width: int, height: int, fmin=25.0, fmax=20000.0, floor_db=-95.0) -> Image.Image:
    m = x.mean(axis=1) if x.ndim == 2 else x
    hop = max(1, len(m) // width)
    f, t, Z = sps.stft(m, SR, nperseg=4096, noverlap=4096 - hop, boundary=None, padded=False)
    mag = np.abs(Z)
    mag = mag[:, :width] if mag.shape[1] >= width else np.pad(mag, ((0, 0), (0, width - mag.shape[1])))
    ldb = 20 * np.log10(mag + 1e-12)
    ldb -= ldb.max()
    rows = np.geomspace(fmax, fmin, height)
    img = np.empty((height, width))
    for i, fr in enumerate(rows):
        lo, hi = fr / 2 ** (1 / 48), fr * 2 ** (1 / 48)
        sel = (f >= lo) & (f <= hi)
        if sel.any():
            img[i] = ldb[sel].max(axis=0)
        else:
            j = np.searchsorted(f, fr)
            img[i] = ldb[min(j, len(f) - 1)]
    v = (img - floor_db) / -floor_db
    return Image.fromarray(_cmap(v), "RGB"), rows


def overview_png(path: Path, x: np.ndarray, scenes: list[dict], title: str, voice: np.ndarray | None = None,
                 marks: list[tuple[float, str]] | None = None, vol: np.ndarray | None = None) -> None:
    W, HS, HW, HL = 1880, 360, 200, 120
    pad_top, gap = 34, 8
    H = pad_top + HS + gap + HW + gap + HL + 30
    im = Image.new("RGB", (W + 70, H), (12, 13, 16))
    dr = ImageDraw.Draw(im)
    fnt, small = _font(15), _font(12)
    dr.text((70, 8), title, fill=(236, 238, 241), font=fnt)
    spec, rows = spectrogram_img(x, W, HS)
    im.paste(spec, (70, pad_top))
    for fr in (50, 100, 200, 500, 1000, 2000, 4000, 8000, 16000):
        yy = pad_top + int(np.argmin(np.abs(rows - fr)))
        dr.line([(64, yy), (70, yy)], fill=(160, 160, 170))
        dr.text((4, yy - 7), f"{fr if fr < 1000 else str(fr // 1000) + 'k'}", fill=(160, 160, 170), font=small)
    # waveform
    y0 = pad_top + HS + gap
    mid = y0 + HW // 2
    m = x.mean(axis=1) if x.ndim == 2 else x
    cols = np.array_split(np.arange(len(m)), W)
    for i, c in enumerate(cols):
        seg = m[c]
        a, b = seg.min(), seg.max()
        r = np.sqrt(np.mean(seg ** 2))
        dr.line([(70 + i, mid - int(b * HW / 2)), (70 + i, mid - int(a * HW / 2))], fill=(90, 110, 140))
        dr.line([(70 + i, mid - int(r * HW / 2)), (70 + i, mid + int(r * HW / 2))], fill=(170, 200, 235))
        if voice is not None:
            vs = voice[c]
            vr = np.sqrt(np.mean(vs ** 2))
            dr.point((70 + i, mid - int(min(1, vr * 3) * HW / 2)), fill=(217, 240, 74))
    dr.text((4, mid - 7), "wave", fill=(160, 160, 170), font=small)
    # short-term loudness (400 ms momentary, K-weighted) and the ducking volume
    y1 = y0 + HW + gap
    k = k_weight(x if x.ndim == 2 else np.stack([x, x], 1))
    p = np.sum(k ** 2, axis=1)
    from scipy.ndimage import uniform_filter1d
    mom = -0.691 + 10 * np.log10(uniform_filter1d(p, nsamp(0.4)) + 1e-12)
    pts = []
    for i, c in enumerate(cols):
        v = mom[c[len(c) // 2]]
        yy = y1 + int(np.clip((-6 - v) / 44, 0, 1) * HL)
        pts.append((70 + i, yy))
    dr.line(pts, fill=(240, 160, 60), width=1)
    for ref in (-10, -16, -26, -40):
        yy = y1 + int((-6 - ref) / 44 * HL)
        dr.line([(70, yy), (70 + W, yy)], fill=(50, 52, 60))
        dr.text((4, yy - 7), f"{ref} LU", fill=(160, 160, 170), font=small)
    if vol is not None:
        vpts = [(70 + i, y1 + HL - int(vol[c[len(c) // 2]] * HL)) for i, c in enumerate(cols)]
        dr.line(vpts, fill=(110, 200, 140), width=1)
    # scenes
    for s in scenes:
        xx = 70 + int(s["start"] / len(m) * W)
        dr.line([(xx, pad_top), (xx, y1 + HL)], fill=(236, 238, 241), width=1)
        dr.text((xx + 3, pad_top + 2), s["id"], fill=(236, 238, 241), font=small)
    for t, label in marks or []:
        xx = 70 + int(t * SR / len(m) * W)
        dr.line([(xx, y1 + HL), (xx, y1 + HL + 8)], fill=(217, 240, 74))
    # time axis
    for sec in range(0, int(len(m) / SR) + 1, 2):
        xx = 70 + int(sec * SR / len(m) * W)
        dr.text((xx, y1 + HL + 10), f"{sec}s", fill=(130, 130, 140), font=small)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def music_volume(tl: dict, n: int) -> np.ndarray:
    """Per-sample copy of Launch.tsx musicVolume() (linear between frames)."""
    BASE, DUCK = 0.62, 0.3
    nf = n // FRAME + 2
    f = np.arange(nf, dtype=float)
    v = np.full(nf, BASE)
    for s in tl["scenes"]:
        a, b = s["vo"]["at"], s["vo"]["speechEnd"]
        d = np.interp(f, [a - 10, a, b, b + 14], [0, 1, 1, 0])
        v = np.minimum(v, BASE - (BASE - DUCK) * d)
    return np.interp(np.arange(n) / FRAME, f, v)


def _decoded_vo(mp3_rel: str, lang: str) -> Path:
    """Voice file -> a WAV read_wav() can load. WAVs are used as they are (read_wav resamples);
    MP3s are decoded to 48 kHz mono under out/audio/vo/<lang>/ (Remotion's bundled ffmpeg)."""
    import subprocess
    src = ROOT / "public" / mp3_rel
    if src.suffix.lower() == ".wav":
        return src
    wav = OUT / "vo" / lang / f"{Path(mp3_rel).stem}.wav"
    if not wav.exists() or wav.stat().st_mtime < src.stat().st_mtime:
        wav.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(f'npx remotion ffmpeg -y -loglevel error -i "{src}" -ar 48000 -ac 1 "{wav}"', cwd=ROOT,
                       shell=True, check=True)
    return wav


def voice_track(tl: dict, lang: str, n: int) -> np.ndarray:
    v = np.zeros(n)
    for s in tl["scenes"]:
        if not s.get("vo"):
            continue
        w = read_wav(_decoded_vo(s["vo"]["file"], lang)).mean(axis=1)
        st = s["vo"]["at"] * FRAME
        e = min(n, st + len(w))
        if e > st:
            v[st:e] += w[: e - st]
    return v


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-20))


def mix_check(lang: str, music: np.ndarray, tl: dict) -> dict:
    n = len(music)
    vol = music_volume(tl, n)
    m = music * vol[:, None]
    try:
        v = voice_track(tl, lang, n)
    except Exception as e:  # missing/undecodable voice: report it, keep the other checks
        return {"skipped": f"voice files could not be read ({e})", "music_ducked_lufs": round(lufs_integrated(m), 1)}
    if np.max(np.abs(v)) < 1e-4:
        # placeholders (estimated timeline): nothing to measure against; still write the ducked music
        write_wav(OUT / f"mix-check.{lang}.wav", m)
        overview_png(OUT / f"mix-check.{lang}.png", m, [dict(id=s["id"], start=s["start"] * FRAME) for s in tl["scenes"]],
                     f"mix check {lang}: music x Launch.tsx ducking (voice files are silent placeholders)", vol=vol)
        return {"skipped": "voice files are silent placeholders (estimated timeline); run again once the real voice exists",
                "music_ducked_lufs": round(lufs_integrated(m), 1)}
    V = np.stack([v, v], axis=1)  # Remotion plays the mono voice on both channels
    mix = m + V
    pk = np.max(np.abs(mix))
    write_wav(OUT / f"mix-check.{lang}.wav", mix / max(1.0, pk / 0.95))
    # speech mask: 50 ms voice RMS within 30 dB of its loud parts
    env = rms_env(v, 0.05)
    thr = np.percentile(env[env > 1e-4], 90) * undb_(-30)
    mask = env > thr
    res = {}
    res["speech_seconds"] = round(mask.sum() / SR, 2)
    res["broadband_db"] = round(db(_rms(V[mask])) - db(_rms(m[mask])), 2)
    kV, kM = k_weight(V), k_weight(m)
    res["k_weighted_db"] = round(db(_rms(kV[mask])) - db(_rms(kM[mask])), 2)
    bV, bM = bp(bp(V, 2000, 0.5), 2000, 0.5), bp(bp(m, 2000, 0.5), 2000, 0.5)
    res["band_1to4k_db"] = round(db(_rms(bV[mask])) - db(_rms(bM[mask])), 2)
    # worst 400 ms speech windows (K-weighted)
    w = nsamp(0.4)
    ratios, times = [], []
    for s0 in range(0, n - w, w // 2):
        mk = mask[s0:s0 + w]
        if mk.mean() > 0.6:
            ratios.append(db(_rms(kV[s0:s0 + w][mk])) - db(_rms(kM[s0:s0 + w][mk])))
            times.append(s0 / SR)
    ratios = np.array(ratios)
    worst = np.argsort(ratios)[:6]
    res["k_weighted_worst_windows"] = [(round(times[i], 2), round(float(ratios[i]), 1)) for i in worst]
    res["k_weighted_window_p10_db"] = round(float(np.percentile(ratios, 10)), 2)
    res["k_weighted_window_min_db"] = round(float(ratios.min()), 2)
    # per scene (K-weighted)
    per = {}
    for s in tl["scenes"]:
        a, b = s["start"] * FRAME, min(n, (s["start"] + s["duration"]) * FRAME)
        mk = mask[a:b]
        if mk.sum() > 0:
            per[s["id"]] = round(db(_rms(kV[a:b][mk])) - db(_rms(kM[a:b][mk])), 1)
    res["k_weighted_per_scene_db"] = per
    res["mix_lufs"] = round(lufs_integrated(mix), 1)
    res["voice_lufs"] = round(lufs_integrated(V), 1)
    res["music_ducked_lufs"] = round(lufs_integrated(m), 1)
    overview_png(OUT / f"mix-check.{lang}.png", mix, [dict(id=s["id"], start=s["start"] * FRAME) for s in tl["scenes"]],
                 f"mix check {lang}: music x Launch.tsx ducking + voice (lime = voice RMS, green = music volume)",
                 voice=v, vol=vol)
    return res


def undb_(d):
    return 10 ** (d / 20)


def report(lang: str, y: np.ndarray, song) -> dict:
    tl = song.tl
    n = len(y)
    scenes = [dict(id=s["id"], start=s["start"] * FRAME, end=(s["start"] + s["duration"]) * FRAME) for s in tl["scenes"]]
    stats = dict(
        lang=lang,
        seconds=round(n / SR, 4),
        frames_expected=tl["durationInFrames"],
        samples=n,
        lufs_integrated=round(lufs_integrated(y), 2),
        true_peak_dbtp=round(db(true_peak(y)), 2),
        sample_peak_dbfs=round(db(np.max(np.abs(y))), 2),
        dc_offset=[float(f"{v:.2e}") for v in y.mean(axis=0)],
        clipped_samples=int(np.sum(np.abs(y) >= 0.999)),
        first_10ms_peak_db=round(db(np.max(np.abs(y[:nsamp(0.01)])) + 1e-9), 1),
        last_frame_rms_db=round(db(_rms(y[-FRAME:])) , 1),
        last_250ms_peak_db=round(db(np.max(np.abs(y[-nsamp(0.25):])) + 1e-9), 1),
        side_below_120hz_db=None,
    )
    from dsp import lp
    lo = lp(lp(y, 120), 120)
    lo80 = lp(lp(y, 80), 80)
    stats["side_below_80hz_db"] = round(db(_rms((lo80[:, 0] - lo80[:, 1]) / 2)) - db(_rms((lo80[:, 0] + lo80[:, 1]) / 2)), 1)
    stats["side_below_120hz_db"] = round(db(_rms((lo[:, 0] - lo[:, 1]) / 2)) - db(_rms((lo[:, 0] + lo[:, 1]) / 2)), 1)
    sec = {}
    for s in scenes:
        seg = y[s["start"]: s["end"]]
        sec[s["id"]] = dict(t=f"{s['start'] / SR:.2f}-{s['end'] / SR:.2f}s", peak_dbfs=round(db(np.max(np.abs(seg))), 1),
                            rms_dbfs=round(db(_rms(seg)), 1), lufs=round(lufs_integrated(seg), 1))
    stats["sections"] = sec
    # level right before / after each scene start (shows section changes)
    edges = {}
    for s in scenes[1:]:
        a = s["start"]
        edges[s["id"]] = dict(before_rms=round(db(_rms(y[a - nsamp(0.5): a])), 1), after_rms=round(db(_rms(y[a: a + nsamp(0.5)])), 1))
    stats["scene_edges"] = edges
    # frame accuracy: offset of the sharpest onset (1.5 kHz+ envelope rise) within +-60 ms of each scene
    # start; 0 ms = the section change lands exactly on the scene's frame 0
    from scipy.ndimage import uniform_filter1d
    from dsp import hp
    # (rise = 3 ms HF energy after vs 3 ms before; the largest relative jump in the window)
    hf = hp(y.mean(axis=1), 1500) ** 2
    w3 = nsamp(0.003)
    c = np.concatenate([[0.0], np.cumsum(hf)])
    onsets, rises = {}, {}
    for s in scenes:
        a, w = s["start"], nsamp(0.06)
        idx = np.arange(max(w3, a - w), min(n - w3, a + w))
        after = c[idx + w3] - c[idx]
        before = c[idx] - c[idx - w3]
        r = 10 * np.log10((after + 1e-12) / (before + 1e-12))
        j = int(np.argmax(r))
        onsets[s["id"]] = round((idx[j] - a) / SR * 1000, 2)
        rises[s["id"]] = round(float(r[a - idx[0]]), 1) if idx[0] <= a <= idx[-1] else None
    stats["onset_offset_ms"] = onsets
    stats["rise_at_scene_start_db"] = rises
    # hard stops before hits: how silent the gap is (before the reverse suck) and how loud the suck gets
    stops = []
    for a, b in getattr(song, "stops", []):
        g0, g1 = a + nsamp(0.012), max(a + nsamp(0.014), b - nsamp(0.45))  # the suck fills the last 0.45 s
        gap = y[g0:g1]
        stops.append(dict(at=f"{a / SR:.2f}-{b / SR:.2f}s", gap_peak_db=round(db(np.max(np.abs(gap)) + 1e-9), 1),
                          last_150ms_rms_db=round(db(_rms(y[b - nsamp(0.15): b])), 1),
                          hit_100ms_rms_db=round(db(_rms(y[b: b + nsamp(0.1)])), 1)))
    stats["stops"] = stops
    stats["stem_rms_db"] = {k: round(v, 1) for k, v in sorted(song.stem_levels.items())}
    stats["mix_check"] = mix_check(lang, y, tl)
    stats["events"] = [(round(t, 2), e) for t, e in song.events]
    overview_png(OUT / f"music.{lang}.png", y, scenes, f"music.{lang}.wav  {stats['lufs_integrated']} LUFS  TP {stats['true_peak_dbtp']} dBTP",
                 marks=song.events)
    (OUT / f"music.{lang}.stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps(stats, indent=1))
    return stats


def sfx_png(path: Path) -> None:
    import sfx
    names = list(sfx.SFX)
    W, H = 600, 150
    rows = (len(names) + 2) // 3
    im = Image.new("RGB", (W * 3 + 40, (H * 2 + 30) * rows + 20), (12, 13, 16))
    dr = ImageDraw.Draw(im)
    fnt = _font(13)
    for i, nme in enumerate(names):
        x = read_wav(ROOT / f"public/audio/sfx/{nme}.wav")
        cx, cy = 10 + (i % 3) * (W + 10), 10 + (i // 3) * (H * 2 + 30)
        spec, _ = spectrogram_img(np.pad(x, ((0, max(0, 8192 - len(x))), (0, 0))), W, H, floor_db=-90)
        im.paste(spec, (cx, cy + 18))
        m = x.mean(axis=1)
        mid = cy + 18 + H + H // 2
        cols = np.array_split(np.arange(len(m)), W)
        for j, c in enumerate(cols):
            if len(c) == 0:
                continue
            a, b = m[c].min(), m[c].max()
            dr.line([(cx + j, mid - int(b * H / 2)), (cx + j, mid - int(a * H / 2))], fill=(170, 200, 235))
        dr.text((cx, cy), f"{nme}  {len(x) / SR * 1000:.0f} ms  peak {db(np.max(np.abs(x))):.1f} dBFS", fill=(236, 238, 241), font=fnt)
    im.save(path)
