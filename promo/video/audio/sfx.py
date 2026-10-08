"""Sound effects for the Paladex launch ad (48 kHz stereo, 16 bit).

click tick pop swipe whoosh whoosh-soft impact riser shimmer   (the original set, v2: punchier)
hit whip rise-short                                            (new in v2)

Modern product-film style: tight transients, real low-end weight on the hits, whooshes
with body and an audible pass-by (rising in, doppler pitch drop, pan across the peak),
clean tails. Every file is normalised to its own true-peak target (all <= -1.5 dBTP) so
the set keeps a sensible balance at the same `volume` in the scenes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from dsp import (SR, add_at, bp, convolve, db, fade, hp, lp, make_ir, noise, nsamp, saw, stereo, sweep, true_peak,
                 undb, write_wav)

PEAK_DB = -1.5  # default true-peak target per file (<= -1 dBTP with margin)

_rng = np.random.default_rng(424242)


def _t(n):
    return np.arange(n) / SR


def _norm(x: np.ndarray, peak_db: float = PEAK_DB) -> np.ndarray:
    tp = true_peak(x)
    return x * (undb(peak_db) / tp)


def _sat(x: np.ndarray, drive: float = 1.5) -> np.ndarray:
    return np.tanh(x * drive) / np.tanh(drive)


def _phase_sin(f: np.ndarray) -> np.ndarray:
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def _pan(x: np.ndarray, p: np.ndarray | float) -> np.ndarray:
    """Equal-power pan with a per-sample pan curve (-1 left .. +1 right)."""
    a = (np.asarray(p) + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1) * np.sqrt(2)


def _end_fade(x: np.ndarray, seconds: float) -> np.ndarray:
    n = nsamp(seconds)
    y = x.copy()
    w = np.cos(np.linspace(0, np.pi / 2, n)) ** 2
    y[-n:] *= w[:, None] if y.ndim == 2 else w
    return y


def _mono_low(y: np.ndarray, f: float = 120.0) -> np.ndarray:
    """Make everything below f mono (keeps hits centred and phase-safe)."""
    lo = lp(lp(y, f), f)
    return y - lo + lo.mean(axis=1, keepdims=True)


def _room(x: np.ndarray, seconds: float, mix: float, seed: int, damp: float = 7000, lo_cut: float = 350) -> np.ndarray:
    ir = make_ir(seconds, predelay=0.003, damp_hz=damp, lo_cut=lo_cut, decay_hz_end=damp * 0.45, er=True, seed=seed)
    n = len(x)
    wet = convolve(x, ir)
    out = np.zeros((n + len(ir), 2))
    out[:n] += stereo(x) if x.ndim == 1 else x
    out[: len(wet)] += wet * mix
    return out


def _trim(y: np.ndarray, seconds: float) -> np.ndarray:
    return y[: nsamp(seconds)]


# ------------------------------------------------------------------ UI

def click() -> np.ndarray:
    """Crisp modern UI click (~70 ms): sharp contact transient, a bright pitched 'tock'
    and a short low body so it has weight, in a tiny room."""
    n = nsamp(0.06)
    t = _t(n)
    contact = bp(hp(noise(n), 2500), 6800, 0.9) * np.exp(-t / 0.0006)
    tock = _phase_sin(1850 + 1500 * np.exp(-t / 0.0018)) * np.exp(-t / 0.0045)
    body = _phase_sin(190 + 150 * np.exp(-t / 0.002)) * (1 - np.exp(-t / 0.0004)) * np.exp(-t / 0.005)
    x = contact * 1.25 + tock * 0.6 + body * 0.42
    x = _sat(x, 1.6)
    x = fade(x, 0.00015, 0.01)
    y = _room(x, 0.16, 0.07, seed=3, damp=9000, lo_cut=500)
    y = _trim(y, 0.07)
    return _norm(_end_fade(y, 0.02), -4.0)


def tick() -> np.ndarray:
    """Tiny high tick (~35 ms), crisp and dry, with a touch of presence."""
    n = nsamp(0.035)
    t = _t(n)
    x = np.sin(2 * np.pi * 5400 * t) * np.exp(-t / 0.0017) * 0.7
    x += hp(noise(n), 6500) * np.exp(-t / 0.0006) * 0.7
    x += np.sin(2 * np.pi * 2700 * t) * np.exp(-t / 0.0024) * 0.35
    x += _phase_sin(900 + 600 * np.exp(-t / 0.001)) * np.exp(-t / 0.003) * 0.18
    x = fade(x, 0.0001, 0.008)
    return _norm(stereo(x), -3.5)


def pop() -> np.ndarray:
    """Satisfying round pop (~170 ms): lip transient, a fast upward 'bloop' and a soft low
    thump under it."""
    n = nsamp(0.17)
    t = _t(n)
    f = 190 + 640 * (1 - np.exp(-t / 0.0095))
    ph = 2 * np.pi * np.cumsum(f) / SR
    env = (1 - np.exp(-t / 0.0007)) * np.exp(-t / 0.026)
    body = np.sin(ph) * env
    harm = 0.28 * np.sin(2 * ph) * env * np.exp(-t / 0.012)
    lip = bp(noise(n), 3200, 1.6) * np.exp(-t / 0.0006) * 0.45
    thump = _phase_sin(140 - 40 * (1 - np.exp(-t / 0.01))) * (1 - np.exp(-t / 0.0006)) * np.exp(-t / 0.012) * 0.38
    x = body + harm + lip + thump
    x = _sat(x, 1.35)
    x = lp(x, 8000)
    x = fade(x, 0.0002, 0.03)
    y = _room(x, 0.3, 0.09, seed=5, damp=6500, lo_cut=350)
    y = _trim(y, 0.17)
    return _norm(_end_fade(y, 0.05), -3.5)


def swipe() -> np.ndarray:
    """Short defined swish (~280 ms) panning left to right: fast rise, bright peak, quick
    fall, with a low 'air push' layer for body."""
    n = nsamp(0.28)
    t = _t(n)
    u = t / t[-1]
    pk = 0.42
    shape = np.where(u < pk, (u / pk) ** 1.4, ((1 - u) / (1 - pk)) ** 0.8)
    fc = 1100 * (5.0 ** shape)
    hiss = sweep(noise(n), fc, "bp", q=1.0, block=32)
    whistle = sweep(noise(n), fc * 0.62, "bp", q=7.0, block=32) * 0.9
    air = sweep(noise(n), 300 + 900 * shape, "lp", q=0.8, block=64) * 0.8
    env = np.where(u < pk, (u / pk) ** 1.8, np.exp(-((u - pk) / (1 - pk)) * 4.0))
    x = (hiss + whistle + air) * env
    x = hp(x, 180)
    p = np.tanh((u - pk) * 5.0) * 0.6
    y = _pan(x, p)
    y = _room(fade(y, 0.002, 0.02), 0.35, 0.12, seed=8, damp=7000, lo_cut=500)
    y = _trim(y, 0.34)
    return _norm(_end_fade(y, 0.05), -1.8)


def _whoosh(dur: float, tp: float, speed: float, closest: float, bands: tuple, whistle_hz: float, body: float,
            rumble: float, verb: float, seed: int, width: float, tail: float) -> np.ndarray:
    """Physical-ish pass-by. A source moves past the listener at `speed` (closest distance
    `closest`): level ~ 1/distance, doppler pitch drop through the pass, pan sweeping across
    the peak, brighter when close (air absorption). Layers: air bands, a racket-string
    'whistle' (narrow band that carries the audible pitch drop), a low body and a sub rumble."""
    n = nsamp(dur)
    t = _t(n)
    x_pos = speed * (t - tp)
    d = np.sqrt(closest ** 2 + x_pos ** 2)
    amp = (closest / d) ** 1.6
    vr = x_pos / d                               # radial velocity / speed (>0 moving away)
    dop = 1.0 / (1.0 + vr * 0.17)                # exaggerated doppler: ~6 semitones across the pass
    dop = dop / dop[nsamp(tp)]
    bright = 600 + 9000 * amp ** 1.2
    y = np.zeros(n)
    for fc, q, g in bands:
        y += sweep(noise(n), fc * dop * (0.75 + 0.5 * amp), "bp", q=q, block=32) * g
    y = sweep(y, bright, "lp", q=0.7, block=64)
    wh = sweep(noise(n), whistle_hz * dop, "bp", q=9.0, block=32) * 2.0 * amp ** 0.5
    bod = sweep(noise(n), 160 + 520 * amp, "lp", q=0.9, block=64) * body
    rum = _phase_sin(72 * dop) * rumble
    x = (y + wh + bod + rum) * amp
    # faint flutter near the peak (a frame cutting the air)
    x *= 1 - 0.18 * amp * (0.5 + 0.5 * np.sin(2 * np.pi * 34 * t))
    x = hp(x, 40)
    pan = np.tanh(x_pos / closest * 0.9) * width
    st = _pan(x, pan)
    st = fade(st, 0.003, 0.02)
    st = _room(st, 0.9, verb, seed=seed, damp=5500, lo_cut=250)
    st = _trim(st, dur + tail)
    st = _mono_low(st, 100)
    return _end_fade(st, tail * 0.9)


def whoosh() -> np.ndarray:
    """Big pass-by whoosh (~0.85 s, peak at 0.32 s): air with body, a clear doppler drop."""
    y = _whoosh(0.7, 0.32, 6.0, 0.55, ((700, 1.1, 1.0), (1700, 1.6, 0.6), (3800, 2.0, 0.35)), 980.0, 1.1, 0.28, 0.16,
                11, 0.8, 0.16)
    return _norm(y, -1.5)


def whoosh_soft() -> np.ndarray:
    """Gentler, darker whoosh (~0.62 s, peak at 0.26 s) for camera moves and lifts."""
    y = _whoosh(0.52, 0.26, 4.5, 0.6, ((420, 0.9, 1.0), (1000, 1.3, 0.5), (2300, 1.8, 0.2)), 640.0, 1.0, 0.18, 0.12,
                12, 0.55, 0.12)
    return _norm(y, -2.0)


def whip() -> np.ndarray:
    """Fast whip-pan swish (~0.25 s): a very quick upward band sweep that cracks at its peak
    (0.13 s) and snaps off, panning hard across."""
    n = nsamp(0.22)
    t = _t(n)
    u = t / t[-1]
    pk = 0.6
    shape = np.where(u < pk, (u / pk) ** 2.2, ((1 - u) / (1 - pk)) ** 0.6)
    fc = 650 * (11.0 ** shape)
    a = sweep(noise(n), fc, "bp", q=1.2, block=16)
    b = sweep(noise(n), fc * 0.5, "bp", q=5.0, block=16) * 0.8
    c = sweep(noise(n), 250 + 700 * shape, "lp", q=0.8, block=32) * 0.6
    env = np.where(u < pk, (u / pk) ** 2.6, np.exp(-((u - pk) / (1 - pk)) * 5.5))
    x = (a + b + c) * env
    i = nsamp(0.22 * pk)
    crack = np.zeros(n)
    m = n - i
    crack[i:] = hp(noise(m), 2500) * np.exp(-_t(m) / 0.004) * 0.55
    x = hp(x + crack, 200)
    x = _sat(x / np.max(np.abs(x)), 2.2)  # denser swish, same peak
    pan = np.tanh((u - pk) * 7.0) * 0.85
    y = _pan(x, pan)
    y = _room(fade(y, 0.001, 0.01), 0.3, 0.1, seed=14, damp=8000, lo_cut=600)
    y = _trim(y, 0.27)
    return _norm(_end_fade(y, 0.04), -1.5)


# ------------------------------------------------------------------ hits

def hit() -> np.ndarray:
    """Short percussive accent (~0.65 s) for slams/landings: tight low punch, a clap-snare
    crack and a short bright room."""
    n = nsamp(0.42)
    t = _t(n)
    f = 52 + 120 * np.exp(-t / 0.016) + 60 * np.exp(-t / 0.003)
    punch = np.sin(2 * np.pi * np.cumsum(f) / SR) * (1 - np.exp(-t / 0.0004)) * np.exp(-t / 0.095)
    punch = _sat(punch, 1.6)
    knock = _phase_sin(230 + 120 * np.exp(-t / 0.004)) * np.exp(-t / 0.035) * 0.45
    crack = np.zeros(n)
    nz = bp(noise(n), 1900, 0.7) + 0.6 * hp(noise(n), 4500)
    for k, (dt, tau, g) in enumerate(((0.0, 0.004, 0.8), (0.007, 0.004, 0.7), (0.014, 0.05, 0.9))):
        i = nsamp(dt)
        e = np.zeros(n)
        e[i:] = np.exp(-t[: n - i] / tau)
        crack += nz * e * g
    crack = hp(crack, 500)
    x = punch * 1.0 + knock + crack * 0.8
    x = fade(x, 0.0002, 0.03)
    y = _room(x, 0.7, 0.16, seed=17, damp=7500, lo_cut=400)
    y = _trim(y, 0.66)
    y = _mono_low(y, 120)
    return _norm(_end_fade(y, 0.22), -1.5)


def impact() -> np.ndarray:
    """Cinematic drop hit (~2.6 s): a hard kick transient, a saturated sub drop with real
    weight (harmonics so it reads on small speakers), a low 'clang' body, a crack and a long
    dark tail."""
    dur = 2.6
    n = nsamp(dur)
    t = _t(n)
    fk = 46 + 170 * np.exp(-t / 0.022) + 90 * np.exp(-t / 0.003)
    kick = np.sin(2 * np.pi * np.cumsum(fk) / SR) * (1 - np.exp(-t / 0.0004)) * np.exp(-t / 0.16)
    kick = _sat(kick, 2.6)
    fs = 33 + 32 * np.exp(-t / 0.32)
    sub = np.sin(2 * np.pi * np.cumsum(fs) / SR) * (1 - np.exp(-t / 0.004)) * np.exp(-t / 0.85)
    sub = _sat(sub, 2.2)
    clang = sum(np.sin(2 * np.pi * f * t + ph) * g for f, ph, g in ((118.0, 0.0, 0.5), (183.0, 1.0, 0.35),
                                                                   (297.0, 2.0, 0.22), (431.0, 0.5, 0.12)))
    clang = clang * (1 - np.exp(-t / 0.002)) * np.exp(-t / 0.28)
    body = lp(noise(n), 450) * np.exp(-t / 0.16) * 1.4
    burst = lp(noise(n), 4200) * np.exp(-t / 0.045) * 0.7
    crack = hp(noise(n), 2200) * np.exp(-t / 0.012) * 0.5
    dry = kick * 1.0 + sub * 0.9 + clang * 0.35 + body + burst + crack
    dry = fade(dry, 0.0003, 0.05)
    dry = _sat(dry / np.max(np.abs(dry)), 1.8)  # density: shave the transient, keep the weight
    snap = (hp(noise(n), 1800) * np.exp(-t / 0.006) + _phase_sin(95 + 260 * np.exp(-t / 0.004)) * np.exp(-t / 0.02))
    dry = dry + snap * 0.55
    ir = make_ir(2.6, predelay=0.018, damp_hz=3600, lo_cut=90, decay_hz_end=700, seed=21)
    wet = convolve(lp(dry, 5000), ir)[:n]
    y = stereo(dry) * 0.9 + wet * 0.36
    y = hp(y, 24)
    y = _mono_low(y, 120)
    return _norm(_end_fade(y, 0.7), -1.5)


# ------------------------------------------------------------------ build-ups

def _riser(dur: float, f0: float, f1: float, m0_hz: float, octaves: float, gate: tuple[float, float], seed: int) -> np.ndarray:
    n = nsamp(dur)
    t = _t(n)
    u = t / dur
    curve = u ** 2.0
    fc = f0 * (f1 / f0) ** curve
    nz = np.stack([sweep(noise(n), fc, "bp", q=1.3, block=32), sweep(noise(n), fc * 1.03, "bp", q=1.3, block=32)], axis=1)
    air = np.stack([hp(noise(n), 5000), hp(noise(n), 5000)], axis=1) * (u ** 3)[:, None] * 0.35
    fp = m0_hz * 2 ** (octaves * u ** 1.6)
    tone = np.zeros((n, 2))
    for d, pan in ((0.993, -0.65), (1.0, 0.0), (1.007, 0.65)):
        tone += stereo(saw(fp * d, n), pan) * 0.33
    tone = sweep(tone, np.minimum(400 + 7000 * curve, 9500), "lp", q=1.1, block=64)
    # rhythmic gate locked to 120 BPM: 16ths -> 32nds (pulses on the grid), deeper towards the end
    rate = gate[0] + (gate[1] - gate[0]) * (u > 0.5)
    ph = np.cumsum(rate) / SR
    g = 0.5 - 0.5 * np.cos(2 * np.pi * ph)
    trem = 1 - (0.15 + 0.5 * u) * g ** 2
    env = (u ** 2.4) * trem
    y = (nz * 0.85 + tone * 0.5 + air) * env[:, None]
    y = hp(y, 140)
    return fade(y, 0.03, 0.004)


def riser() -> np.ndarray:
    """2 s riser (4 beats at 120 BPM): noise + pitched saws climbing, gated on 16ths then 32nds;
    peaks at the very end and stops dead (4 ms) into the next hit."""
    return _norm(_riser(2.0, 220, 10000, 110.0, 3.0, (8.0, 16.0), 31), -1.5)


def rise_short() -> np.ndarray:
    """0.5 s riser (one beat): a quick suck-up into a hit, gated on 32nds, stops dead."""
    return _norm(_riser(0.5, 700, 11000, 220.0, 2.0, (16.0, 32.0), 32), -1.5)


def shimmer() -> np.ndarray:
    """Airy bright sparkle (~1.2 s): crisp glints of high partials in A over a rising air sweep."""
    dur = 1.2
    n = nsamp(dur)
    t = _t(n)
    y = np.zeros((n, 2))
    partials = [1760.0, 2217.5, 2637.0, 3520.0, 4434.9, 5274.0, 7040.0]
    for i in range(28):
        f = partials[_rng.integers(len(partials))] * (1 + _rng.normal(0, 0.002))
        st = nsamp(0.5 * (i / 28) ** 1.4 + _rng.uniform(0, 0.04))
        ln = nsamp(0.45)
        tt = _t(ln)
        g = (1 - np.exp(-tt / 0.0012)) * np.exp(-tt / _rng.uniform(0.07, 0.18)) * _rng.uniform(0.3, 0.65) * (1 - i / 36)
        v = np.sin(2 * np.pi * f * tt + _rng.uniform(0, 6)) * g
        add_at(y, stereo(v, float(_rng.uniform(-0.8, 0.8))), st)
    u = t / dur
    air = sweep(noise(n), 4000 * (2.5 ** np.clip(u / 0.5, 0, 1)), "bp", q=0.8, block=64)
    air_env = np.sin(np.pi * np.clip(u / 0.65, 0, 1)) ** 2 * 0.3
    y += stereo(air * air_env)
    y = lp(y, 13000)
    ir = make_ir(1.4, predelay=0.012, damp_hz=9000, lo_cut=1200, decay_hz_end=4000, seed=33)
    y = y + convolve(y, ir) * 0.4
    y = fade(y, 0.001, 0.05)
    return _norm(_end_fade(y, 0.35), -3.0)


SFX = {
    "click": click,
    "tick": tick,
    "pop": pop,
    "swipe": swipe,
    "whoosh": whoosh,
    "whoosh-soft": whoosh_soft,
    "impact": impact,
    "riser": riser,
    "shimmer": shimmer,
    "hit": hit,
    "whip": whip,
    "rise-short": rise_short,
}


def render_all(out_dir: Path) -> dict[str, dict]:
    report = {}
    for name, fn in SFX.items():
        x = fn()
        assert x.ndim == 2 and x.shape[1] == 2
        target = db(true_peak(x))
        x = _norm(_end_fade(hp(x, 18), 0.003), target)  # remove DC from asymmetric transients
        assert db(true_peak(x)) <= -1.0 + 1e-6, name
        write_wav(out_dir / f"{name}.wav", x)
        k = x.mean(axis=1)
        # loudest 50 ms (K-ish proxy: plain RMS) -> how loud it reads at the same volume
        w = nsamp(0.05)
        r = np.sqrt(np.convolve(k ** 2, np.ones(w) / w, mode="valid").max())
        report[name] = {
            "seconds": round(len(x) / SR, 3),
            "peak_dbfs": round(db(np.max(np.abs(x))), 2),
            "true_peak_dbfs": round(db(true_peak(x)), 2),
            "max_rms50ms_db": round(db(r), 1),
            "crest_db": round(db(np.max(np.abs(x))) - db(r), 1),
            "dc": float(np.round(np.abs(x.mean(axis=0)).max(), 6)),
            "end_level_db": round(db(np.max(np.abs(x[-nsamp(0.005):])) + 1e-9), 1),
        }
    return report
