"""Small DSP toolkit for the Paladex music bed and sound effects (numpy + scipy).

Everything works on float64 arrays at SR = 48 kHz. Mono signals are 1-D arrays,
stereo signals are (n, 2) arrays.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from scipy import signal as sps
from scipy.ndimage import maximum_filter1d, uniform_filter1d

SR = 48_000
RNG = np.random.default_rng(20261007)


# ---------------------------------------------------------------- basics

def secs(n: int) -> float:
    return n / SR


def nsamp(t: float) -> int:
    return int(round(t * SR))


def db(x: float) -> float:
    return 20 * np.log10(max(x, 1e-12))


def undb(d: float) -> float:
    return 10 ** (d / 20)


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
        "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def n2m(name: str) -> int:
    """'A4' -> 69, 'C#5' -> 73."""
    p, o = (name[:2], name[2:]) if len(name) > 2 and name[1] in "#b" else (name[:1], name[1:])
    return NOTE[p] + 12 * (int(o) + 1)


def stereo(x: np.ndarray, pan: float = 0.0) -> np.ndarray:
    """Equal-power pan of a mono signal (-1 left .. +1 right)."""
    if x.ndim == 2:
        return x
    a = (pan + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1) * np.sqrt(2)


def mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def add_at(dst: np.ndarray, src: np.ndarray, start: int, gain: float = 1.0) -> None:
    """Mix `src` into `dst` starting at sample `start` (clipped to bounds)."""
    if src.ndim == 1 and dst.ndim == 2:
        src = np.stack([src, src], axis=1)
    if start >= len(dst):
        return
    s0 = max(0, -start)
    d0 = max(0, start)
    n = min(len(src) - s0, len(dst) - d0)
    if n > 0:
        dst[d0:d0 + n] += src[s0:s0 + n] * gain


# ---------------------------------------------------------------- envelopes

def adsr(n: int, a: float, d: float, s: float, r: float, gate: float | None = None, curve: float = 4.0) -> np.ndarray:
    """ADSR of n samples. `gate` = seconds the note is held (default: n minus release).
    Exponential-ish segments (curve > 0)."""
    t = np.arange(n) / SR
    g = gate if gate is not None else max(0.0, n / SR - r)
    env = np.empty(n)

    def seg(x, k):
        return (1 - np.exp(-k * x)) / (1 - np.exp(-k)) if k > 0 else x

    a = max(a, 1e-4)
    d = max(d, 1e-4)
    att = t < a
    env[att] = seg(t[att] / a, curve * 0.5)
    dec = (t >= a) & (t < a + d)
    env[dec] = 1 - (1 - s) * seg((t[dec] - a) / d, curve)
    sus = t >= a + d
    env[sus] = s
    # level at gate release
    if g < a:
        lg = seg(g / a, curve * 0.5)
    elif g < a + d:
        lg = 1 - (1 - s) * seg((g - a) / d, curve)
    else:
        lg = s
    rel = t >= g
    r = max(r, 1e-4)
    x = np.clip((t[rel] - g) / r, 0, 1)
    env[rel] = lg * (1 - seg(x, curve))
    return env


def exp_decay(n: int, tau: float) -> np.ndarray:
    return np.exp(-np.arange(n) / SR / tau)


def fade(x: np.ndarray, fin: float = 0.002, fout: float = 0.005) -> np.ndarray:
    """Short raised-cosine fades at both ends (declick)."""
    y = x.copy()
    ni, no = nsamp(fin), nsamp(fout)
    if ni > 0:
        w = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ni))
        y[:ni] *= w if y.ndim == 1 else w[:, None]
    if no > 0:
        w = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, no))
        y[-no:] *= w if y.ndim == 1 else w[:, None]
    return y


# ---------------------------------------------------------------- oscillators

def _phase(freq, n: int, phase0: float = 0.0) -> np.ndarray:
    f = np.broadcast_to(np.asarray(freq, dtype=float), (n,))
    ph = phase0 + np.cumsum(f) / SR
    return ph - np.floor(ph), f / SR


def _polyblep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    out[m] = x + x - x * x - 1
    m2 = t > 1 - dt
    x = (t[m2] - 1) / dt[m2]
    out[m2] = x * x + x + x + 1
    return out


def saw(freq, n: int, phase0: float | None = None) -> np.ndarray:
    """Band-limited (PolyBLEP) sawtooth, -1..1."""
    p0 = RNG.random() if phase0 is None else phase0
    t, dt = _phase(freq, n, p0)
    return (2 * t - 1) - _polyblep(t, dt)


def square(freq, n: int, pw: float = 0.5, phase0: float | None = None) -> np.ndarray:
    p0 = RNG.random() if phase0 is None else phase0
    t, dt = _phase(freq, n, p0)
    sq = np.where(t < pw, 1.0, -1.0)
    sq += _polyblep(t, dt)
    t2 = (t + 1 - pw) % 1.0
    sq -= _polyblep(t2, dt)
    return sq


def sine(freq, n: int, phase0: float = 0.0) -> np.ndarray:
    t, _ = _phase(freq, n, phase0)
    return np.sin(2 * np.pi * t)


def tri(freq, n: int, phase0: float | None = None) -> np.ndarray:
    p0 = RNG.random() if phase0 is None else phase0
    t, _ = _phase(freq, n, p0)
    return 4 * np.abs(t - 0.5) - 1


def noise(n: int, ch: int = 1) -> np.ndarray:
    x = RNG.standard_normal((n, ch)) if ch > 1 else RNG.standard_normal(n)
    return x


def supersaw(freq: float, n: int, voices: int = 5, detune_cents: float = 14.0, spread: float = 0.8) -> np.ndarray:
    """Detuned saw stack, returned as stereo (n, 2)."""
    out = np.zeros((n, 2))
    for i in range(voices):
        k = (i - (voices - 1) / 2) / max(1, (voices - 1) / 2)  # -1..1
        f = freq * 2 ** (k * detune_cents / 1200)
        drift = 1 + 0.0015 * np.sin(2 * np.pi * (0.13 + 0.07 * i) * np.arange(n) / SR + RNG.random() * 6)
        v = saw(f * drift, n)
        out += stereo(v, k * spread) * (1.0 if i == (voices - 1) // 2 else 0.8)
    return out / (voices * 0.85)


# ---------------------------------------------------------------- filters

def _rbj(kind: str, f0: float, q: float = 0.707, gain_db: float = 0.0):
    f0 = float(np.clip(f0, 10, SR * 0.49))
    w = 2 * np.pi * f0 / SR
    cw, sw = np.cos(w), np.sin(w)
    alpha = sw / (2 * q)
    A = 10 ** (gain_db / 40)
    if kind == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bp":
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "lowshelf":
        sa = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sa)]
        a = [(A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]
    elif kind == "highshelf":
        sa = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa)]
        a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    else:
        raise ValueError(kind)
    b, a = np.array(b), np.array(a)
    return b / a[0], a / a[0]


def biquad(x: np.ndarray, kind: str, f0: float, q: float = 0.707, gain_db: float = 0.0) -> np.ndarray:
    b, a = _rbj(kind, f0, q, gain_db)
    return sps.lfilter(b, a, x, axis=0)


def lp(x, f, q=0.707):
    return biquad(x, "lp", f, q)


def hp(x, f, q=0.707):
    return biquad(x, "hp", f, q)


def bp(x, f, q=1.0):
    return biquad(x, "bp", f, q)


def peak(x, f, gain_db, q=1.0):
    return biquad(x, "peak", f, q, gain_db)


def shelf_lo(x, f, gain_db, q=0.707):
    return biquad(x, "lowshelf", f, q, gain_db)


def shelf_hi(x, f, gain_db, q=0.707):
    return biquad(x, "highshelf", f, q, gain_db)


def lp24(x, f, q=0.707):
    return lp(lp(x, f, q), f, 0.54)


def sweep(x: np.ndarray, cutoff, kind: str = "lp", q: float = 0.707, block: int = 128) -> np.ndarray:
    """Fast time-varying biquad: coefficients updated every `block` samples,
    filter state carried across blocks (DF2T via lfilter zi). Good for slow-to-
    moderate sweeps (filter opening over bars, risers)."""
    mono_in = x.ndim == 1
    X = x[:, None] if mono_in else x
    n, ch = X.shape
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), (n,))
    Y = np.empty_like(X)
    zi = np.zeros((2, ch))
    for s in range(0, n, block):
        e = min(n, s + block)
        fc = float(np.exp(np.mean(np.log(np.maximum(cutoff[s:e], 10)))))
        b, a = _rbj(kind, fc, q)
        Y[s:e], zi = sps.lfilter(b, a, X[s:e], axis=0, zi=zi)
    return Y[:, 0] if mono_in else Y


# ---------------------------------------------------------------- effects

def saturate(x: np.ndarray, drive: float = 1.0) -> np.ndarray:
    return np.tanh(x * drive) / np.tanh(drive)


def chorus(x: np.ndarray, depth_ms: float = 4.0, rate: float = 0.35, mix: float = 0.5, base_ms: float = 12.0) -> np.ndarray:
    """Stereo chorus: two modulated delay taps in quadrature, one per side."""
    X = stereo(x) if x.ndim == 1 else x
    n = len(X)
    t = np.arange(n) / SR
    out = X.copy() * (1 - mix * 0.5)
    for c, ph in ((0, 0.0), (1, np.pi / 2)):
        d = (base_ms + depth_ms * 0.5 * (1 + np.sin(2 * np.pi * rate * t + ph))) * SR / 1000
        idx = np.arange(n) - d
        src = X[:, c]
        wet = np.interp(idx, np.arange(n), src, left=0.0)
        out[:, c] += wet * mix
    return out


def widen(x: np.ndarray, width: float = 1.3) -> np.ndarray:
    m = (x[:, 0] + x[:, 1]) / 2
    s = (x[:, 0] - x[:, 1]) / 2 * width
    return np.stack([m + s, m - s], axis=1)


def mono_below(x: np.ndarray, f: float = 120.0) -> np.ndarray:
    """Remove the side (L-R) component below f (zero-phase 4th-order high-pass on the side
    signal only), so the low end is mono while the mid signal is untouched."""
    m = (x[:, 0] + x[:, 1]) / 2
    s = (x[:, 0] - x[:, 1]) / 2
    sos = sps.butter(2, f, "highpass", fs=SR, output="sos")
    s = sps.sosfiltfilt(sos, s)
    return np.stack([m + s, m - s], axis=1)


def make_ir(seconds: float = 2.4, predelay: float = 0.018, damp_hz: float = 6500.0, lo_cut: float = 180.0,
            decay_hz_end: float = 1800.0, er: bool = True, seed: int = 7) -> np.ndarray:
    """Synthetic stereo hall IR: decorrelated noise, exponential decay (RT60 = seconds),
    frequency-dependent damping (gets darker over time), early reflections."""
    rng = np.random.default_rng(seed)
    n = nsamp(seconds * 1.15)
    t = np.arange(n) / SR
    env = 10 ** (-3 * t / seconds)  # -60 dB at `seconds`
    ir = rng.standard_normal((n, 2)) * env[:, None]
    # darker over time: crossfade between bright and dark versions
    dark = lp(lp(ir, decay_hz_end), decay_hz_end)
    bright = lp(ir, damp_hz)
    w = np.clip(t / (seconds * 0.6), 0, 1)[:, None]
    ir = bright * (1 - w) + dark * w
    ir = hp(ir, lo_cut)
    # fade-in of the diffuse tail (build-up)
    ir *= (1 - np.exp(-t / 0.035))[:, None]
    if er:
        for k in range(10):
            dt = rng.uniform(0.004, 0.06)
            g = 0.55 * (1 - k / 12) * rng.uniform(0.5, 1.0)
            i = nsamp(dt)
            ir[i, 0] += g * rng.choice([-1, 1])
            i2 = nsamp(dt * rng.uniform(0.85, 1.2))
            ir[i2, 1] += g * rng.choice([-1, 1])
    pd = nsamp(predelay)
    ir = np.concatenate([np.zeros((pd, 2)), ir])
    ir /= np.sqrt(np.sum(ir ** 2) / 2)
    return ir


def convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """Stereo convolution (true-stereo-ish: L->L, R->R, with a little cross-feed)."""
    X = stereo(x) if x.ndim == 1 else x
    n = len(X)
    yl = sps.oaconvolve(X[:, 0] * 0.85 + X[:, 1] * 0.15, ir[:, 0])[:n]
    yr = sps.oaconvolve(X[:, 1] * 0.85 + X[:, 0] * 0.15, ir[:, 1])[:n]
    return np.stack([yl, yr], axis=1)


def reverb(x: np.ndarray, ir: np.ndarray, mix: float) -> np.ndarray:
    return (stereo(x) if x.ndim == 1 else x) + convolve(x, ir) * mix


def pingpong(x: np.ndarray, delay_s: float, feedback: float = 0.45, taps: int = 8, lp_hz: float = 4500.0,
             hp_hz: float = 300.0) -> np.ndarray:
    """Wet-only ping-pong delay: each repeat alternates side and gets darker."""
    X = mono(x)
    n = len(X)
    out = np.zeros((n, 2))
    d = nsamp(delay_s)
    y = hp(X, hp_hz)
    for k in range(1, taps + 1):
        y = lp(y, lp_hz)
        g = feedback ** (k - 1)
        sh = d * k
        if sh >= n:
            break
        side = 0 if k % 2 else 1
        out[sh:, side] += y[:n - sh] * g
        out[sh:, 1 - side] += y[:n - sh] * g * 0.25
    return out


# ---------------------------------------------------------------- dynamics

def rms_env(x: np.ndarray, window: float) -> np.ndarray:
    p = mono(x) ** 2 if x.ndim == 1 else np.mean(x ** 2, axis=1)
    w = max(1, nsamp(window))
    return np.sqrt(uniform_filter1d(p, w) + 1e-20)


def compress(x: np.ndarray, threshold_db: float = -18.0, ratio: float = 2.0, attack: float = 0.01,
             release: float = 0.15, knee_db: float = 6.0, makeup_db: float = 0.0) -> np.ndarray:
    """Feed-forward RMS bus compressor with soft knee; stereo-linked."""
    p = np.mean(x ** 2, axis=1) if x.ndim == 2 else x ** 2
    # attack/release smoothing in power domain
    ra = np.exp(-1 / (attack * SR))
    rr = np.exp(-1 / (release * SR))
    # two-stage: fast attack-smoothed then release-smoothed (vectorised approximation)
    pa = sps.lfilter([1 - ra], [1, -ra], p)
    pr = sps.lfilter([1 - rr], [1, -rr], p)
    pe = np.maximum(pa, pr)
    lvl = 10 * np.log10(pe + 1e-20)
    over = lvl - threshold_db
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                           (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * knee_db)))
    g = 10 ** ((-gr + makeup_db) / 20)
    # smooth gain to avoid zipper
    g = sps.lfilter([1 - ra], [1, -ra], g - 1) + 1
    return x * (g[:, None] if x.ndim == 2 else g)


def true_peak(x: np.ndarray, os: int = 4) -> float:
    X = x if x.ndim == 2 else x[:, None]
    up = sps.resample_poly(X, os, 1, axis=0)
    return float(np.max(np.abs(up)))


def limiter(x: np.ndarray, ceiling_db: float = -1.2, lookahead: float = 0.004, release: float = 0.08,
            os: int = 4) -> np.ndarray:
    """Look-ahead true-peak brickwall limiter. Gain is computed on the 4x oversampled
    signal, smoothed (min-hold over the look-ahead + one-pole release + moving average)
    and applied at the base rate after delaying the signal by the look-ahead."""
    ceil = undb(ceiling_db)
    X = x if x.ndim == 2 else x[:, None]
    up = sps.resample_poly(X, os, 1, axis=0)
    pk = np.max(np.abs(up), axis=1).reshape(-1, os).max(axis=1)[:len(X)]
    if len(pk) < len(X):
        pk = np.pad(pk, (0, len(X) - len(pk)))
    L = max(1, nsamp(lookahead))
    need = np.minimum(1.0, ceil / np.maximum(pk, 1e-12))
    # min over the look-ahead window ending at each sample (so gain falls before the peak)
    from scipy.ndimage import minimum_filter1d
    g = minimum_filter1d(need, size=2 * L + 1, origin=0)
    rc = np.exp(-1 / (release * SR))
    # release: the gain may only rise slowly -> process as envelope of (1-g)
    r = 1 - g
    r = np.maximum(r, sps.lfilter([1 - rc], [1, -rc], r))
    # smooth with moving average of the look-ahead length (keeps it below need)
    r = maximum_filter1d(r, size=2 * L + 1)
    r = uniform_filter1d(r, size=L)
    g = 1 - r
    y = X * g[:, None]
    # final safety: soft clip anything that still pokes over
    y = np.where(np.abs(y) > ceil * 0.98, np.sign(y) * (ceil * 0.98 + (ceil * 0.02) * np.tanh((np.abs(y) - ceil * 0.98) / (ceil * 0.02))), y)
    return y if x.ndim == 2 else y[:, 0]


def soft_clip(x: np.ndarray, knee: float = 0.8) -> np.ndarray:
    """Transparent below `knee`, smoothly saturating above."""
    a = np.abs(x)
    over = a > knee
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((a[over] - knee) / (1 - knee)))
    return y


# ---------------------------------------------------------------- loudness (ITU-R BS.1770-4)

def k_weight(x: np.ndarray) -> np.ndarray:
    X = x if x.ndim == 2 else x[:, None]
    # stage 1: high shelf +4 dB @ ~1681 Hz ; stage 2: RLB high-pass @ ~38 Hz (48 kHz coefficients)
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    return sps.lfilter(b2, a2, sps.lfilter(b1, a1, X, axis=0), axis=0)


def lufs_integrated(x: np.ndarray) -> float:
    y = k_weight(x)
    blk, hop = nsamp(0.4), nsamp(0.1)
    ms = []
    for s in range(0, len(y) - blk + 1, hop):
        ms.append(np.sum(np.mean(y[s:s + blk] ** 2, axis=0)))
    ms = np.array(ms)
    if len(ms) == 0:
        return -70.0
    l = -0.691 + 10 * np.log10(ms + 1e-20)
    g = ms[l > -70]
    if len(g) == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(np.mean(g)) - 10
    g2 = ms[(l > -70) & (l > rel)]
    return float(-0.691 + 10 * np.log10(np.mean(g2)))


def lufs_short(x: np.ndarray, window: float = 3.0, hop: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
    """Short-term loudness curve (times, LUFS)."""
    y = k_weight(x)
    p = np.sum(y ** 2, axis=1)
    w = nsamp(window)
    m = uniform_filter1d(p, w, origin=(w // 2) - 1 if w % 2 == 0 else w // 2)  # trailing window
    idx = np.arange(0, len(p), nsamp(hop))
    return idx / SR, -0.691 + 10 * np.log10(m[idx] + 1e-20)


# ---------------------------------------------------------------- io

def write_wav(path: Path | str, x: np.ndarray, bits: int = 16) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    X = stereo(x) if x.ndim == 1 else x
    X = np.clip(X, -1, 1)
    # TPDF dither to 16 bit
    lsb = 1 / 32768
    d = (RNG.random(X.shape) - RNG.random(X.shape)) * lsb
    q = np.clip(np.round((X + d) * 32767), -32768, 32767).astype("<i2")
    # write to a temp file and swap it in, so a failed write (e.g. disk full) never
    # leaves a truncated file where Remotion reads it
    tmp = path.with_name(path.name + ".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(q.tobytes())
    expected = 44 + q.size * 2
    if tmp.stat().st_size != expected:
        tmp.unlink(missing_ok=True)
        raise IOError(f"short write for {path} (disk full?)")
    import os
    os.replace(tmp, path)


def read_wav(path: Path | str) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    assert sw == 2, "16-bit only"
    x = np.frombuffer(raw, dtype="<i2").astype(float) / 32768
    x = x.reshape(-1, ch)
    if sr != SR:
        from math import gcd
        gg = gcd(sr, SR)
        x = sps.resample_poly(x, SR // gg, sr // gg, axis=0)
    return x
