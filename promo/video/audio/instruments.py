"""Instrument voices for the Paladex music bed. Each returns a mono (n,) or stereo
(n, 2) float array for ONE note/hit; the arranger places them on the timeline."""
from __future__ import annotations

import numpy as np

from dsp import (SR, add_at, bp, exp_decay, fade, hp, lp, lp24, midi_hz, noise, nsamp, peak, saw, sine, square,
                 stereo, supersaw, sweep, tri, adsr)

_rng = np.random.default_rng(1207)


def _t(n):
    return np.arange(n) / SR


# ------------------------------------------------------------------ drums

def kick(vel: float = 1.0, long: bool = False) -> np.ndarray:
    """Punchy, round kick tuned to A (55 Hz)."""
    n = nsamp(0.9 if long else 0.42)
    t = _t(n)
    f = 55 + 175 * np.exp(-t / 0.028) + 40 * np.exp(-t / 0.006)
    ph = 2 * np.pi * np.cumsum(f) / SR
    amp = (1 - np.exp(-t / 0.0008)) * np.exp(-t / (0.32 if long else 0.13))
    body = np.sin(ph) * amp
    body = np.tanh(body * 1.8) / np.tanh(1.8)
    click = bp(noise(n), 3200, 0.9) * np.exp(-t / 0.0018) * 0.22
    x = body + click
    x = lp(x, 9000)
    return fade(x, 0.0, 0.02) * vel


def clap(vel: float = 1.0) -> np.ndarray:
    """Soft clap: a few noise bursts + short body (mono, reverb added by the bus)."""
    n = nsamp(0.32)
    t = _t(n)
    x = np.zeros(n)
    nz = bp(noise(n), 1350, 0.9) + 0.35 * bp(noise(n), 2600, 1.2)
    for k, dt in enumerate((0.0, 0.0095, 0.0195, 0.027)):
        i = nsamp(dt)
        e = np.zeros(n)
        e[i:] = np.exp(-(t[: n - i]) / (0.0045 if k < 3 else 0.11))
        x += nz * e * (0.85 if k < 3 else 0.55)
    x = hp(x, 600)
    x = lp(x, 7000)
    return fade(x, 0.0003, 0.03) * vel


def snare_roll_hit(vel: float = 1.0) -> np.ndarray:
    """Short soft snare for rolls/fills."""
    n = nsamp(0.18)
    t = _t(n)
    tone = np.sin(2 * np.pi * (190 + 40 * np.exp(-t / 0.01)) * t) * np.exp(-t / 0.035) * 0.5
    nz = bp(noise(n), 3000, 0.7) * np.exp(-t / 0.05)
    x = hp(tone + nz, 150)
    return fade(x, 0.0003, 0.02) * vel


def hat(vel: float = 1.0, open_: bool = False) -> np.ndarray:
    """Closed/open hat: metallic square partials + noise, high-passed."""
    n = nsamp(0.35 if open_ else 0.08)
    t = _t(n)
    metal = np.zeros(n)
    for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0):
        metal += square(f * 3.2, n, phase0=_rng.random())
    x = bp(metal, 9500, 1.2) * 0.45 + hp(noise(n), 7500) * 0.8
    env = (1 - np.exp(-t / 0.0006)) * np.exp(-t / (0.11 if open_ else 0.024))
    x = hp(x * env, 6500)
    return fade(x, 0.0, 0.01) * vel


def shaker(vel: float = 1.0) -> np.ndarray:
    n = nsamp(0.07)
    t = _t(n)
    env = (1 - np.exp(-t / 0.006)) * np.exp(-t / 0.018)
    x = bp(noise(n), 7800, 1.3) * env
    return fade(x, 0.0, 0.01) * vel


def data_click(vel: float = 1.0, pitch: float = 1.0) -> np.ndarray:
    """Tiny high 'data' click for the specs groove (above the voice band)."""
    n = nsamp(0.04)
    t = _t(n)
    x = np.sin(2 * np.pi * 5200 * pitch * t) * np.exp(-t / 0.004) * 0.6
    x += hp(noise(n), 6000) * np.exp(-t / 0.0015) * 0.5
    return fade(x, 0.0, 0.005) * vel


def tom(vel: float, f0: float) -> np.ndarray:
    n = nsamp(0.4)
    t = _t(n)
    f = f0 * (1 + 0.6 * np.exp(-t / 0.02))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.16)
    x += lp(noise(n), 2500) * np.exp(-t / 0.01) * 0.15
    return fade(x, 0.0, 0.03) * vel


def crash(vel: float = 1.0, dur: float = 2.2) -> np.ndarray:
    """Soft filtered crash (stereo)."""
    n = nsamp(dur)
    t = _t(n)
    xs = []
    for _ in range(2):
        metal = np.zeros(n)
        for f in (311.0, 433.0, 587.0, 742.0, 911.0, 1259.0):
            metal += square(f * 2.7 * (1 + _rng.normal(0, 0.01)), n, phase0=_rng.random())
        x = bp(metal, 7000, 0.7) * 0.25 + hp(noise(n), 4500)
        env = (1 - np.exp(-t / 0.002)) * (0.75 * np.exp(-t / 0.45) + 0.25 * np.exp(-t / 1.2))
        x = lp(hp(x * env, 3500), 12000)
        xs.append(x)
    y = np.stack(xs, axis=1)
    return fade(y, 0.0, 0.2) * vel


# ------------------------------------------------------------------ tonal

def sub(m: float, n: int, vel: float = 1.0) -> np.ndarray:
    """Clean sine sub with soft attack/release (mono)."""
    x = sine(midi_hz(m), n) + 0.12 * sine(2 * midi_hz(m), n)
    env = adsr(n, 0.006, 0.05, 0.92, 0.05)
    return x * env * vel


def midbass(m: float, n: int, vel: float = 1.0) -> np.ndarray:
    """Warm mid bass: detuned saw + square, 24 dB low-pass with a pluck envelope."""
    f = midi_hz(m)
    total = n + nsamp(0.08)
    t = _t(total)
    x = 0.6 * saw(f * 1.002, total) + 0.5 * square(f * 0.998, total, pw=0.42) + 0.5 * sine(f / 2, total)
    cut = 240 + 950 * np.exp(-t / 0.07) * vel
    y = sweep(x, cut, "lp", q=0.9, block=32)
    y = lp(y, 1800)
    env = adsr(total, 0.003, 0.12, 0.6, 0.06, gate=n / SR)
    y = np.tanh(y * env * 1.6) / np.tanh(1.6)
    return y * vel


def pad_chord(midis: list[float], n: int, attack: float = 0.15, release: float = 0.7) -> np.ndarray:
    """Wide supersaw chord (stereo), un-filtered (the bus filters it)."""
    total = n + nsamp(release)
    y = np.zeros((total, 2))
    for i, m in enumerate(midis):
        y += supersaw(midi_hz(m), total, voices=5, detune_cents=11, spread=0.85) * (0.9 if i == 0 else 0.75)
    env = adsr(total, attack, 0.6, 0.85, release, gate=n / SR, curve=3.0)
    return y * env[:, None] / max(1, len(midis)) * 1.6


def pluck(m: float, n: int, vel: float = 1.0, bright: float = 1.0) -> np.ndarray:
    """Soft plucked synth (stereo): two detuned saws, filter envelope, short tail."""
    f = midi_hz(m)
    total = n + nsamp(0.35)
    t = _t(total)
    l = 0.7 * saw(f * 1.0035, total) + 0.35 * square(f, total, pw=0.3)
    r = 0.7 * saw(f * 0.9965, total) + 0.35 * square(f, total, pw=0.3)
    cut = 420 + bright * 3800 * np.exp(-t / 0.055) + 500 * np.exp(-t / 0.4)
    x = sweep(np.stack([l, r], axis=1), cut, "lp", q=0.8, block=32)
    env = adsr(total, 0.0015, 0.32, 0.18, 0.25, gate=n / SR, curve=4.0)
    x = x * env[:, None]
    x = peak(x, 2600, -4.0, 0.9)
    return x * vel * 0.8


def bell(m: float, n: int, vel: float = 1.0, ring: float = 1.4) -> np.ndarray:
    """FM bell / glassy EP (mono): ratio-2 modulator with decaying index, plus a faint inharmonic partial."""
    f = midi_hz(m)
    total = n + nsamp(ring * 2.2)
    t = _t(total)
    idx = 1.0 * np.exp(-t / 0.15) + 0.15
    modu = np.sin(2 * np.pi * 2 * f * t)
    x = np.sin(2 * np.pi * f * t + idx * modu)
    x += 0.12 * np.sin(2 * np.pi * 3.51 * f * t) * np.exp(-t / 0.25)
    env = (1 - np.exp(-t / 0.002)) * np.exp(-t / ring)
    rel = np.ones(total)
    g = n / SR + ring
    rel[t > g] = np.exp(-(t[t > g] - g) / 0.3)
    x = lp(x * env * rel, 7000)
    return fade(x, 0.0, 0.05) * vel * 0.6


def glass(m: float, n: int, vel: float = 1.0) -> np.ndarray:
    """Arp tone: triangle + sine octave, gentle low-pass, short decay (mono)."""
    f = midi_hz(m)
    total = n + nsamp(0.25)
    t = _t(total)
    x = 0.7 * tri(f, total) + 0.3 * sine(2 * f, total)
    env = (1 - np.exp(-t / 0.002)) * np.exp(-t / 0.13)
    x = lp(x * env, 3200)
    return fade(x, 0.0, 0.03) * vel * 0.7


def lead(m: float, n: int, vel: float = 1.0) -> np.ndarray:
    """Soft sine lead (mono) for octave doubling."""
    f = midi_hz(m)
    total = n + nsamp(0.3)
    t = _t(total)
    vib = 1 + 0.0025 * np.sin(2 * np.pi * 5.0 * t) * np.clip(t / 0.25, 0, 1)
    x = sine(f * vib, total) + 0.18 * sine(2 * f * vib, total)
    env = adsr(total, 0.012, 0.2, 0.55, 0.25, gate=n / SR)
    return x * env * vel * 0.6


# ------------------------------------------------------------------ atmospheres / fx

def drone(n: int, root: float = 33.0) -> np.ndarray:
    """Dark low drone (stereo): detuned saws on A1/A2 + fifth, filter slowly opening."""
    t = _t(n)
    f1 = midi_hz(root)
    y = np.zeros((n, 2))
    for d, pan, g in ((0.997, -0.7, 0.5), (1.003, 0.7, 0.5), (2.0 * 1.001, -0.3, 0.35), (2.0 * 0.999, 0.3, 0.35),
                      (3.0, 0.0, 0.15)):
        y += stereo(saw(f1 * d, n), pan) * g
    u = t / t[-1]
    cut = 140 * (4.5 ** (u ** 1.3))
    y = sweep(y, cut, "lp", q=1.1, block=256)
    y += stereo(sine(f1, n)) * 0.35
    breath = 0.82 + 0.18 * np.sin(2 * np.pi * 0.25 * t - np.pi / 2)
    return y * breath[:, None]


def heartbeat(vel: float = 1.0, double: bool = True) -> np.ndarray:
    """Sub 'lub-dub' thump (mono)."""
    n = nsamp(0.7)
    t = _t(n)
    x = np.zeros(n)
    for dt, g in ((0.0, 1.0), (0.24, 0.6)) if double else ((0.0, 1.0),):
        i = nsamp(dt)
        tt = t[: n - i]
        f = 42 + 26 * np.exp(-tt / 0.03)
        v = np.sin(2 * np.pi * np.cumsum(f) / SR) * (1 - np.exp(-tt / 0.004)) * np.exp(-tt / 0.11)
        x[i:] += v * g
    x = lp(x, 160)
    return fade(x, 0.0, 0.05) * vel


def clock_tick(vel: float, high: bool) -> np.ndarray:
    n = nsamp(0.05)
    t = _t(n)
    f = 4600 if high else 3300
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.0035)
    x += bp(noise(n), f * 1.4, 2.0) * np.exp(-t / 0.0015) * 0.5
    x = hp(x, 2200)
    return fade(x, 0.0, 0.01) * vel


def tension_pad(midis: list[float], n: int) -> np.ndarray:
    total = n
    y = np.zeros((total, 2))
    for i, m in enumerate(midis):
        y += supersaw(midi_hz(m), total, voices=3, detune_cents=18, spread=0.9)
    return y / len(midis)


def noise_riser(n: int, f0: float = 250.0, f1: float = 8000.0, q: float = 1.2, power: float = 2.0) -> np.ndarray:
    t = _t(n)
    u = t / t[-1]
    fc = f0 * (f1 / f0) ** (u ** power)
    l = sweep(noise(n), fc, "bp", q=q, block=64)
    r = sweep(noise(n), fc * 1.02, "bp", q=q, block=64)
    env = u ** 2.4
    return np.stack([l, r], axis=1) * env[:, None]


def pitch_riser(n: int, m0: float, octaves: float) -> np.ndarray:
    t = _t(n)
    u = t / t[-1]
    f = midi_hz(m0) * 2 ** (octaves * u ** 1.7)
    y = np.zeros((n, 2))
    for d, pan in ((0.995, -0.7), (1.0, 0.0), (1.005, 0.7)):
        y += stereo(saw(f * d, n), pan) / 3
    y = sweep(y, np.minimum(300 + 5000 * u ** 2, 9000), "lp", q=0.9, block=64)
    return y * (u ** 2.0)[:, None]


def reverse_swell(seconds: float, ir: np.ndarray, bright: float = 6000.0) -> np.ndarray:
    """Reverse cymbal-ish swell that ends with a sharp cut (stereo)."""
    n = nsamp(seconds)
    burst = hp(noise(nsamp(0.08)), 2500) * np.exp(-_t(nsamp(0.08)) / 0.02)
    from dsp import convolve
    src = np.zeros(n + nsamp(0.1))
    src[: len(burst)] = burst
    wet = convolve(src, ir)[:n]
    y = wet[::-1].copy()
    y = lp(y, bright)
    y *= (np.linspace(0, 1, n) ** 1.5)[:, None]
    y = fade(y, 0.01, 0.004)
    return y / (np.max(np.abs(y)) + 1e-9)


def sub_drop(seconds: float = 1.6, f0: float = 90.0, f1: float = 30.0) -> np.ndarray:
    n = nsamp(seconds)
    t = _t(n)
    f = f1 + (f0 - f1) * np.exp(-t / 0.25)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * (1 - np.exp(-t / 0.003)) * np.exp(-t / 0.55)
    x = np.tanh(x * 1.5) / np.tanh(1.5)
    return fade(x, 0.0, 0.2)


def boom(seconds: float = 1.2) -> np.ndarray:
    n = nsamp(seconds)
    t = _t(n)
    x = lp(noise(n), 300) * np.exp(-t / 0.18) * 2.0 + lp(noise(n), 3000) * np.exp(-t / 0.03) * 0.6
    return fade(x, 0.0, 0.2)
