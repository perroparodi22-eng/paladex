"""Sound effects for the Paladex launch ad (48 kHz stereo, 16 bit).

click, tick, pop, swipe, whoosh, whoosh-soft, impact, riser, shimmer.
Premium UI-film style: soft transients, short tails, nothing harsh.
Each file is peak-normalised so its true peak sits at PEAK_DB.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from dsp import (SR, add_at, bp, convolve, db, exp_decay, fade, hp, lp, make_ir, noise, nsamp, peak,
                 saw, sine, stereo, sweep, true_peak, undb, write_wav)

PEAK_DB = -3.5  # true peak target per file (task: <= -3 dBFS)

_rng = np.random.default_rng(424242)


def _t(n):
    return np.arange(n) / SR


def _norm(x: np.ndarray, peak_db: float = PEAK_DB) -> np.ndarray:
    tp = true_peak(x)
    return x * (undb(peak_db) / tp)


def _pan_sweep(x: np.ndarray, p0: float, p1: float, curve: np.ndarray | None = None) -> np.ndarray:
    n = len(x)
    p = p0 + (p1 - p0) * (np.linspace(0, 1, n) if curve is None else curve)
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1) * np.sqrt(2)


def _end_fade(x: np.ndarray, seconds: float) -> np.ndarray:
    n = nsamp(seconds)
    y = x.copy()
    w = np.cos(np.linspace(0, np.pi / 2, n)) ** 2
    y[-n:] *= w[:, None] if y.ndim == 2 else w
    return y


# ------------------------------------------------------------------ UI

def click() -> np.ndarray:
    """Crisp, soft UI click (~60 ms): a damped high transient over a tiny woody body."""
    n = nsamp(0.06)
    t = _t(n)
    trans = bp(noise(n), 4200, 1.4) * np.exp(-t / 0.0014)
    tone = np.sin(2 * np.pi * 2350 * t) * np.exp(-t / 0.006) * 0.35
    body = np.sin(2 * np.pi * (520 - 160 * np.exp(-t / 0.004)) * t) * np.exp(-t / 0.011) * 0.45
    x = trans * 0.9 + tone + body
    x = lp(x, 9000)
    x = fade(x, 0.0003, 0.01)
    ir = make_ir(0.25, predelay=0.002, damp_hz=7000, lo_cut=400, decay_hz_end=3500, er=True, seed=3)
    y = stereo(x) + convolve(x, ir)[:n] * 0.12
    return _norm(_end_fade(y, 0.02))


def tick() -> np.ndarray:
    """Tiny high tick (~30 ms)."""
    n = nsamp(0.03)
    t = _t(n)
    x = np.sin(2 * np.pi * 6200 * t) * np.exp(-t / 0.0022) * 0.7
    x += hp(noise(n), 7000) * np.exp(-t / 0.0009) * 0.6
    x += np.sin(2 * np.pi * 3100 * t) * np.exp(-t / 0.003) * 0.2
    x = fade(x, 0.0002, 0.008)
    return _norm(stereo(x), PEAK_DB - 2)


def pop() -> np.ndarray:
    """Soft bubbly pop (~150 ms): a fast upward pitch blip with a round body."""
    n = nsamp(0.16)
    t = _t(n)
    f = 260 + 760 * (1 - np.exp(-t / 0.018))
    ph = 2 * np.pi * np.cumsum(f) / SR
    env = (1 - np.exp(-t / 0.0015)) * np.exp(-t / 0.035)
    x = np.sin(ph) * env + 0.18 * np.sin(2 * ph) * env * np.exp(-t / 0.02)
    x += bp(noise(n), 2500, 2.0) * np.exp(-t / 0.0015) * 0.15
    x = lp(x, 6000)
    x = fade(x, 0.0005, 0.03)
    ir = make_ir(0.35, predelay=0.004, damp_hz=6000, lo_cut=300, decay_hz_end=2500, seed=5)
    y = stereo(x) + convolve(x, ir)[:n] * 0.1
    return _norm(_end_fade(y, 0.04), PEAK_DB - 1)


def swipe() -> np.ndarray:
    """Short airy swish (~250 ms), panning left to right."""
    n = nsamp(0.26)
    t = _t(n)
    u = t / t[-1]
    cut = 900 * (6.5 ** np.sin(np.pi * np.clip(u * 1.1, 0, 1)) )
    x = sweep(noise(n), cut, "bp", q=1.1, block=32)
    x += sweep(noise(n), cut * 2.2, "bp", q=2.0, block=32) * 0.35
    env = np.sin(np.pi * u) ** 1.6 * (1 - 0.3 * u)
    x = hp(x * env, 500)
    y = _pan_sweep(x, -0.55, 0.55, 0.5 - 0.5 * np.cos(np.pi * u))
    return _norm(fade(y, 0.002, 0.02))


def _whoosh(dur: float, f_lo: float, f_hi: float, q: float, peak_at: float, rumble: float, verb: float, seed: int,
            width: float) -> np.ndarray:
    n = nsamp(dur)
    t = _t(n)
    u = t / dur
    # doppler-ish: centre frequency rises to the pass-by then falls
    shape = np.where(u < peak_at, (u / peak_at) ** 1.7, ((1 - u) / (1 - peak_at)) ** 0.9)
    fc = f_lo * (f_hi / f_lo) ** shape
    nz = noise(n)
    a = sweep(nz, fc, "bp", q=q, block=32)
    b = sweep(noise(n), fc * 0.5, "lp", q=0.8, block=64) * 0.5
    env = np.where(u < peak_at, (u / peak_at) ** 2.2, np.exp(-((u - peak_at) / (1 - peak_at)) * 3.2))
    x = (a + b) * env
    # low pass-by tone
    fr = 95 * (1 + 0.5 * shape) * np.where(u < peak_at, 1, 1 - 0.35 * (u - peak_at) / (1 - peak_at))
    ph = 2 * np.pi * np.cumsum(fr) / SR
    x += np.sin(ph) * env * rumble
    x = hp(x, 45)
    y = _pan_sweep(x, -width, width, 0.5 - 0.5 * np.cos(np.pi * np.clip(u / (peak_at * 1.6), 0, 1)))
    ir = make_ir(1.0, predelay=0.01, damp_hz=5000, lo_cut=250, decay_hz_end=1500, seed=seed)
    y = y + convolve(y, ir) * verb
    y = fade(y, 0.002, 0.04)
    return _norm(_end_fade(y, 0.12))


def whoosh() -> np.ndarray:
    """Big filtered-noise whoosh with a pass-by pitch sweep (~700 ms)."""
    return _whoosh(0.7, 220, 2600, 1.6, 0.52, 0.22, 0.18, 11, 0.7)


def whoosh_soft() -> np.ndarray:
    """Gentler, darker whoosh (~500 ms)."""
    return _whoosh(0.5, 180, 1300, 0.9, 0.5, 0.10, 0.12, 12, 0.45)


# ------------------------------------------------------------------ cinematic

def impact() -> np.ndarray:
    """Deep cinematic hit: sub drop + noise burst + long dark reverb tail (~2.5 s)."""
    dur = 2.5
    n = nsamp(dur)
    t = _t(n)
    # sub drop: 90 Hz -> 34 Hz
    f = 34 + 56 * np.exp(-t / 0.22)
    ph = 2 * np.pi * np.cumsum(f) / SR
    sub = np.sin(ph) * (1 - np.exp(-t / 0.003)) * np.exp(-t / 0.75)
    sub = np.tanh(sub * 1.6) / np.tanh(1.6)
    # punch: short pitched kick transient
    fk = 55 + 180 * np.exp(-t / 0.02)
    kick = np.sin(2 * np.pi * np.cumsum(fk) / SR) * np.exp(-t / 0.09)
    # noise burst, dark
    burst = lp(noise(n), 3800) * np.exp(-t / 0.06) * 0.8
    body = lp(noise(n), 420) * np.exp(-t / 0.22) * 1.2
    crackle = hp(noise(n), 2500) * np.exp(-t / 0.018) * 0.3
    dry = sub * 1.0 + kick * 0.7 + burst + body + crackle
    dry = fade(dry, 0.0005, 0.05)
    ir = make_ir(2.6, predelay=0.02, damp_hz=3200, lo_cut=90, decay_hz_end=700, seed=21)
    wet = convolve(lp(dry, 5000), ir)
    y = stereo(dry) * 0.9 + wet * 0.55
    y = hp(y, 25)
    # keep the sub mono, tail ends clean
    lo = lp(lp(y, 110), 110)
    y = y - lo + lo.mean(axis=1, keepdims=True)
    return _norm(_end_fade(y, 0.6))


def riser() -> np.ndarray:
    """2 s rising filtered noise + pitch; ends abruptly (5 ms) to lead into an impact."""
    dur = 2.0
    n = nsamp(dur)
    t = _t(n)
    u = t / dur
    curve = u ** 2.2
    fc = 220 * (9000 / 220) ** curve
    nzL = sweep(noise(n), fc, "bp", q=1.4, block=32)
    nzR = sweep(noise(n), fc * 1.03, "bp", q=1.4, block=32)
    nz = np.stack([nzL, nzR], axis=1)
    # pitched layer: A2 -> A5, detuned saws, filtered
    fp = 110 * 8 ** (u ** 1.6)
    tone = np.zeros((n, 2))
    for k, (d, pan) in enumerate(((0.994, -0.6), (1.0, 0.0), (1.006, 0.6))):
        v = saw(fp * d, n)
        tone += stereo(v, pan) * 0.33
    tone = sweep(tone, np.minimum(400 + 6000 * curve, 9000), "lp", q=0.9, block=64)
    trem = 1 - 0.35 * (0.5 + 0.5 * np.sin(2 * np.pi * np.cumsum(3 + 22 * u ** 2) / SR))
    env = (u ** 2.6) * trem
    y = (nz * 0.9 + tone * 0.45) * env[:, None]
    y = hp(y, 120)
    y = fade(y, 0.05, 0.005)
    return _norm(y)


def shimmer() -> np.ndarray:
    """Airy bright sparkle (~1.2 s): glints of high partials in A, with an air swell."""
    dur = 1.2
    n = nsamp(dur)
    t = _t(n)
    y = np.zeros((n, 2))
    partials = [1760.0, 2217.5, 2637.0, 3520.0, 4434.9, 5274.0, 7040.0]
    for i in range(26):
        f = partials[_rng.integers(len(partials))] * (1 + _rng.normal(0, 0.002))
        st = nsamp(0.55 * (i / 26) ** 1.3 + _rng.uniform(0, 0.05))
        ln = nsamp(0.45)
        tt = _t(ln)
        g = (1 - np.exp(-tt / 0.003)) * np.exp(-tt / _rng.uniform(0.08, 0.2)) * _rng.uniform(0.25, 0.6) * (1 - i / 34)
        v = np.sin(2 * np.pi * f * tt + _rng.uniform(0, 6)) * g
        add_at(y, stereo(v, float(_rng.uniform(-0.8, 0.8))), st)
    air = hp(noise(n), 6000)
    u = t / dur
    air_env = np.sin(np.pi * np.clip(u / 0.7, 0, 1)) ** 2 * 0.25
    y += stereo(air * air_env) * np.array([1.0, 1.0]) * 0.6
    y = lp(y, 12000)
    ir = make_ir(1.4, predelay=0.012, damp_hz=9000, lo_cut=1200, decay_hz_end=4000, seed=33)
    y = y + convolve(y, ir) * 0.45
    y = fade(y, 0.002, 0.05)
    return _norm(_end_fade(y, 0.35))


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
}


def render_all(out_dir: Path) -> dict[str, dict]:
    report = {}
    for name, fn in SFX.items():
        x = fn()
        assert x.ndim == 2 and x.shape[1] == 2
        write_wav(out_dir / f"{name}.wav", x)
        report[name] = {
            "seconds": round(len(x) / SR, 3),
            "peak_dbfs": round(db(np.max(np.abs(x))), 2),
            "true_peak_dbfs": round(db(true_peak(x)), 2),
            "dc": float(np.round(np.abs(x.mean(axis=0)).max(), 6)),
            "end_level_db": round(db(np.max(np.abs(x[-nsamp(0.005):])) + 1e-9), 1),
        }
    return report
