"""Paladex launch ad: original music bed + sound effects.

    python audio/make_music.py            # sfx + music + checks
    python audio/make_music.py sfx        # only the sound effects
    python audio/make_music.py music en   # only the English music bed (+ checks)

Writes
    public/audio/sfx/<name>.wav           click tick pop swipe whoosh whoosh-soft impact riser shimmer
    public/audio/music.<lang>.wav         exact length = durationInFrames / 60 s, 48 kHz stereo 16 bit
    out/audio/*                           spectrogram/waveform PNGs, mix checks, stats

Minimal electronic, 120 BPM, A minor. The arrangement is built from
src/data/timeline.<lang>.json so every section change lands exactly on a scene start
(scenes start on the beat grid: 1 beat = 30 frames = 24000 samples).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

import instruments as ins
from dsp import (SR, add_at, chorus, compress, convolve, db, fade, hp, limiter, lp, lufs_integrated, make_ir,
                 mono_below, nsamp, peak, pingpong, saturate, stereo, sweep, true_peak, undb, widen, write_wav)

ROOT = Path(__file__).resolve().parent.parent
FPS = 60
FRAME = SR // FPS          # 800 samples per video frame
SPB = SR // 2              # 24000 samples per beat (120 BPM)
S16 = SPB // 4             # 6000 samples per 16th
SWING = int(0.16 * S16)    # late odd 16ths -> gentle shuffle

TARGET_LUFS = -17.2
CEILING_DBTP = -1.2

# ------------------------------------------------------------------ harmony

CHORDS = {  # sub root (MIDI), pad voicing (MIDI)
    "Am": dict(root=33, pad=[57, 60, 64, 67, 69]),  # A1 | A3 C4 E4 G4 A4   (Am7)
    "F": dict(root=29, pad=[53, 57, 60, 64, 67]),   # F1 | F3 A3 C4 E4 G4   (Fmaj9)
    "C": dict(root=36, pad=[55, 60, 62, 64, 67]),   # C2 | G3 C4 D4 E4 G4   (Cadd9)
    "G": dict(root=31, pad=[55, 59, 62, 67, 69]),   # G1 | G3 B3 D4 G4 A4   (Gadd9)
    "E": dict(root=28, pad=[52, 56, 59, 62, 64]),   # E1 | E3 G#3 B3 D4 E4  (E7, pulls back to Am)
}

# The hook: rising three-note figure (3-3-2 feel) and a falling answer. (16th, MIDI, length in 16ths)
MOTIF = {
    "Am": [(0, 69, 2), (3, 72, 2), (6, 76, 3), (10, 74, 2), (12, 72, 4)],
    "F": [(0, 69, 2), (3, 72, 2), (6, 77, 3), (10, 76, 2), (12, 72, 4)],
    "C": [(0, 67, 2), (3, 72, 2), (6, 76, 3), (10, 74, 2), (12, 76, 4)],
    "G": [(0, 67, 2), (3, 71, 2), (6, 74, 3), (10, 76, 2), (12, 74, 4)],
    "E": [(0, 68, 2), (3, 71, 2), (6, 76, 2)],
}

# Per-scene arrangement of the groove sections.
CFG = {
    "reveal": dict(hat="8", ohat=False, shaker=False, perc=False, bassvar=0, motif="pluck", arp=None, lead=False, cut=(1000, 1700)),
    "turn": dict(hat="16", ohat=True, shaker=False, perc=False, bassvar=1, motif="pluck", arp="A", lead=False, cut=(1700, 2500)),
    "specs": dict(hat="16", ohat=False, shaker=False, perc=True, bassvar=0, motif="bell", arp=None, lead=False, cut=(1500, 1500)),
    "finder": dict(hat="16", ohat=True, shaker=True, perc=False, bassvar=2, motif="pluck", arp="B", lead=False, cut=(1900, 3000)),
    "brands": dict(hat="16", ohat=True, shaker=True, perc=True, bassvar=2, motif="pluck", arp="B", lead=True, cut=(3000, 3800)),
    "endcard": dict(hat="16", ohat=False, shaker=False, perc=False, bassvar=0, motif="pluck", arp=None, lead=False, cut=(2600, 800)),
}
GROOVE = list(CFG)

BASS_PATTERNS = {  # (16th, semitone offset from the mid root)
    0: [(2, 0), (6, 0), (10, 0), (14, 0)],
    1: [(2, 0), (6, 0), (10, 0), (13, 0), (14, 12)],
    2: [(2, 0), (3, 12), (6, 0), (10, 0), (11, 12), (14, 0), (15, 7)],
}

# Stem gains (linear) and bus sends.
GAIN = dict(kick=0.45, sub=0.22, midbass=0.25, pad=0.85, clap=0.75, snare=0.35, tom=0.25, hat=0.26, ohat=0.11,
            shaker=0.18, perc=0.28, motif=0.62, bell=0.13, arp=0.22, lead=0.11, crash=0.06, swell=0.14,
            drone=0.20, heart=0.65, tick=0.24, tension=0.55, riser=0.14, impact=0.70, logo=0.14, air=0.06)
SEND_HALL = dict(pad=0.30, motif=0.28, bell=0.55, arp=0.30, lead=0.45, clap=0.10, logo=0.9, tension=0.40,
                 drone=0.15, tick=0.30, swell=0.2, crash=0.2)
SEND_ROOM = dict(clap=0.30, snare=0.30, tom=0.25, hat=0.10, perc=0.25, shaker=0.08)
SEND_DARK = dict(impact=0.55, heart=0.10, riser=0.25)
SIDECHAIN = dict(sub=(0.92, 0.13), midbass=(0.55, 0.16), pad=(0.5, 0.24), arp=(0.25, 0.2), motif=(0.12, 0.18),
                 lead=(0.2, 0.2), hall=(0.3, 0.25))


def load_timeline(lang: str) -> dict:
    return json.loads((ROOT / f"src/data/timeline.{lang}.json").read_text(encoding="utf-8"))


class Song:
    def __init__(self, lang: str):
        tl = load_timeline(lang)
        assert tl["fps"] == FPS and tl["bpm"] == 120 and tl["beatFrames"] == 30
        self.lang = lang
        self.tl = tl
        self.N = tl["durationInFrames"] * FRAME
        self.L = self.N + nsamp(5.0)
        self.order = [s["id"] for s in tl["scenes"]]
        self.sc = {}
        for s in tl["scenes"]:
            assert s["start"] % 30 == 0 and s["duration"] % 30 == 0, s["id"]
            self.sc[s["id"]] = dict(id=s["id"], b0=s["start"] // 30, beats=s["duration"] // 30,
                                    start=s["start"] * FRAME, end=(s["start"] + s["duration"]) * FRAME, vo=s["vo"])
        self.stems: dict[str, np.ndarray] = defaultdict(lambda: np.zeros((self.L, 2)))
        self.kicks: list[int] = []
        self.irs = dict(
            hall=make_ir(2.8, predelay=0.025, damp_hz=7000, lo_cut=220, decay_hz_end=1600, seed=101),
            room=make_ir(0.6, predelay=0.006, damp_hz=8000, lo_cut=300, decay_hz_end=2500, seed=102),
            dark=make_ir(4.0, predelay=0.03, damp_hz=3000, lo_cut=60, decay_hz_end=600, seed=103),
        )
        self.events: list[tuple[float, str]] = []  # (seconds, label) for the report

    # -------------------------------------------------------------- helpers
    @staticmethod
    def B(beat: float) -> int:
        return int(round(beat * SPB))

    def put(self, stem: str, x: np.ndarray, at: int, gain: float = 1.0) -> None:
        add_at(self.stems[stem], stereo(x) if x.ndim == 1 else x, at, gain)

    def bars(self, sid: str) -> list[dict]:
        s = self.sc[sid]
        full, rem = divmod(s["beats"], 4)
        if sid == "endcard":
            seq = (["Am", "F", "Am"] + ["Am"] * 8)[:full]
        else:
            seq = (["Am", "F", "C", "G"] * 4)[:full]
            if rem == 0 and full == 3:
                seq[-1] = "G"
        out, b = [], s["b0"]
        for i, c in enumerate(seq):
            out.append(dict(scene=sid, i=i, b=b, beats=4, chord=c, last=(i == len(seq) - 1 and rem == 0)))
            b += 4
        if rem:
            out.append(dict(scene=sid, i=len(seq), b=b, beats=rem, chord="E", last=True))
        return out

    def next_scene(self, sid: str) -> str | None:
        i = self.order.index(sid)
        return self.order[i + 1] if i + 1 < len(self.order) else None

    # -------------------------------------------------------------- intro: cold open + problem
    def intro(self) -> None:
        co, pr, rv = self.sc["cold-open"], self.sc["problem"], self.sc["reveal"]
        t_rev = rv["start"]
        # dark drone across both scenes, filter opening, cut at the reveal impact
        n = t_rev
        d = ins.drone(n)
        w = np.ones(n)
        fi = nsamp(1.8)
        w[:fi] = np.sin(np.linspace(0, np.pi / 2, fi)) ** 2
        crescendo = 1 + 0.9 * np.clip((np.arange(n) - pr["start"]) / (t_rev - pr["start"]), 0, 1) ** 2
        d = d * (w * crescendo)[:, None]
        d = fade(d, 0.0, 0.012)
        self.put("drone", d, 0)
        # air: wide, breathing, very quiet
        air = np.stack([lp(hp(np.random.default_rng(5).standard_normal(n), 300), 1400),
                        lp(hp(np.random.default_rng(6).standard_normal(n), 300), 1400)], axis=1)
        tt = np.arange(n) / SR
        air *= (0.5 - 0.5 * np.cos(2 * np.pi * tt / 4.0))[:, None] * w[:, None]
        self.put("air", fade(air, 0.0, 0.012), 0)
        # heartbeat: lub-dub every 2 beats in the cold open, single pulse every beat in the problem
        for b in range(co["b0"], co["b0"] + co["beats"], 2):
            self.put("heart", ins.heartbeat(0.75 + 0.05 * (b - co["b0"]) / 2), self.B(b))
        for k, b in enumerate(range(pr["b0"], pr["b0"] + pr["beats"] - 1)):
            self.put("heart", ins.heartbeat(0.6 + 0.04 * k, double=False), self.B(b))
        # clock-like tick-tock on 8ths through the problem, 16ths ratchet over the last two beats
        b0, nb = pr["b0"], pr["beats"]
        for k in range(nb * 2):
            bt = b0 + k / 2
            if bt >= b0 + nb - 2:
                break
            self.put("tick", stereo(ins.clock_tick(0.55 + 0.25 * (k % 2 == 0), k % 2 == 0), -0.25 if k % 2 else 0.25),
                     self.B(bt))
        for k in range(8):
            bt = b0 + nb - 2 + k / 4
            self.put("tick", stereo(ins.clock_tick(0.4 + 0.08 * k, k % 2 == 0), 0.3 if k % 2 else -0.3), self.B(bt))
        # dissonant pad: A pedal with b9 / b6 cluster, tremolo tightening, filter opening
        n = t_rev - pr["start"]
        tp = ins.tension_pad([45, 52, 58, 60, 65], n)
        u = np.arange(n) / n
        tp = sweep(tp, 280 * (6 ** u), "lp", q=1.0, block=128)
        trem = 1 - (0.15 + 0.35 * u) * (0.5 + 0.5 * np.cos(2 * np.pi * np.cumsum(4 + 4 * u) / SR))
        env = np.clip(np.arange(n) / nsamp(0.8), 0, 1) * (0.7 + 0.6 * u)
        tp = peak(tp, 2400, -7, 0.7) * (trem * env)[:, None]
        self.put("tension", fade(tp, 0.0, 0.01), pr["start"])
        # riser over the last 4 beats, ending abruptly on the reveal's frame 0
        rn = self.B(4)
        r = ins.noise_riser(rn, 300, 9000, 1.3, 2.0) * 0.9 + ins.pitch_riser(rn, 45, 2.0) * 0.6
        self.put("riser", fade(r, 0.02, 0.004), t_rev - rn)
        self.put("swell", ins.reverse_swell(0.5, self.irs["hall"]), t_rev - nsamp(0.5), 1.4)
        self.events += [(co["start"] / SR, "cold-open: drone + heartbeat"), (pr["start"] / SR, "problem: ticks + cluster pad"),
                        ((t_rev - rn) / SR, "riser starts"), (t_rev / SR, "reveal impact")]

    # -------------------------------------------------------------- reveal impact
    def impact(self) -> None:
        t = self.sc["reveal"]["start"]
        self.put("impact", ins.kick(1.0, long=True), t, 1.0)
        self.put("impact", ins.sub_drop(1.8, 85, 31), t, 0.8)
        self.put("impact", ins.boom(1.2), t, 0.35)
        self.put("crash", ins.crash(1.0, 3.0), t, 2.2)
        self.kicks.append(t)

    # -------------------------------------------------------------- groove
    def groove(self) -> None:
        for sid in GROOVE:
            cfg = CFG[sid]
            bars = self.bars(sid)
            nxt = self.next_scene(sid)
            for bar in bars:
                self.groove_bar(sid, cfg, bar, nxt)
            if nxt:
                # reverse swell into the next scene start, 1 beat (2 beats after a half bar)
                ln = 1.0 if bars[-1]["beats"] == 2 else 0.5
                self.put("swell", ins.reverse_swell(ln, self.irs["hall"]), self.sc[nxt]["start"] - nsamp(ln))
                if nxt != "endcard":
                    self.put("crash", ins.crash(0.8), self.sc[nxt]["start"])
            self.events.append((self.sc[sid]["start"] / SR, f"{sid}: chords {' '.join(b['chord'] for b in bars)}"))
        self.logo_hit()

    def groove_bar(self, sid: str, cfg: dict, bar: dict, nxt: str | None) -> None:
        t0 = self.B(bar["b"])
        nb = bar["beats"]
        n16 = nb * 4
        chord = CHORDS[bar["chord"]]
        endcard_tail = sid == "endcard" and bar["i"] >= 1
        fill = bar["last"] and nxt is not None
        pos = lambda k, swing=1.0: t0 + k * S16 + (int(SWING * swing) if k % 2 else 0)

        # ---- pad (always, including the end card tail)
        attack = 0.02 if (sid == "reveal" and bar["i"] == 0) else 0.15
        gate = nb * SPB
        rel = 0.7
        if sid == "endcard" and bar["i"] == 2:
            gate, rel, attack = int(nb * SPB * 0.55), 1.4, 0.4
        self.put("pad", ins.pad_chord(chord["pad"], gate, attack=attack, release=rel), t0)

        # ---- motif
        notes = MOTIF[bar["chord"]]
        if endcard_tail:
            if bar["i"] == 2:
                notes = notes[:3]
            for k, m, ln in notes:
                ring = 2.2 if bar["i"] == 2 else 1.4
                self.put("bell", stereo(ins.bell(m, ln * S16, 0.85, ring=ring), 0.15), pos(k))
        elif cfg["motif"] == "bell":
            for k, m, ln in notes:
                if k in (0, 6, 12):
                    self.put("bell", stereo(ins.bell(m, ln * S16, 0.9), -0.1 if k == 6 else 0.12), pos(k))
        else:
            for j, (k, m, ln) in enumerate(notes):
                if k >= n16:
                    continue
                v = 1.0 if j in (0, 2) else 0.82
                self.put("motif", ins.pluck(m, ln * S16, v, bright=1.0 if sid != "reveal" else 0.8), pos(k))
                if cfg["lead"]:
                    self.put("lead", stereo(ins.lead(m + 12, ln * S16, v), 0.0), pos(k))

        if endcard_tail:
            return

        # ---- arp
        if cfg["arp"]:
            tones = [m + 12 for m in chord["pad"]]
            seq = [0, 1, 2, 3, 4, 3, 2, 1] if cfg["arp"] == "A" else [0, 2, 1, 3, 2, 4, 3, 1]
            for k in range(n16):
                m = tones[seq[k % 8]]
                v = 0.9 if k % 4 == 0 else 0.55 + 0.1 * (k % 2)
                pan = 0.55 * np.sin(2 * np.pi * (k / 16 + bar["b"] / 8))
                self.put("arp", stereo(ins.glass(m, int(S16 * 0.9), v), float(pan)), pos(k, 0.5))

        # ---- bass
        self.put("sub", ins.sub(chord["root"], nb * SPB, 1.0), t0)
        mid_root = chord["root"] + 12
        for k, off in BASS_PATTERNS[cfg["bassvar"]]:
            if k < n16:
                v = 0.95 if off == 0 else 0.7
                self.put("midbass", ins.midbass(mid_root + off, int(S16 * 1.6), v), pos(k, 0.5))

        # ---- drums
        kick_pos = [k for k in range(0, n16, 4)]
        clap_pos = [k for k in (4, 12) if k < n16]
        roll: list[int] = []
        toms: list[tuple[int, float]] = []
        if fill:
            if nb == 2:
                kick_pos = [0]
                clap_pos = []
                roll = [2, 4, 5, 6, 7]
            elif sid == "turn":
                kick_pos = [0, 4, 8]
                clap_pos = [4]
                toms = [(12, 196.0), (14, 147.0), (15, 110.0)]
            elif sid == "specs":
                kick_pos = [0, 4, 8]
                clap_pos = [4]
                roll = [12, 14, 15]
            else:
                roll = [12, 13, 14, 15]
                if sid == "finder":
                    rn = self.B(4)
                    self.put("riser", ins.noise_riser(rn, 500, 9000, 1.0, 2.2), t0 + nb * SPB - rn, 0.6)
        if sid == "reveal" and bar["i"] == 0:
            kick_pos = [k for k in kick_pos if k != 0]  # the impact carries the downbeat
        for k in kick_pos:
            accent = 1.0 if k == 0 else 0.92
            self.put("kick", ins.kick(accent), pos(k))
            self.kicks.append(pos(k))
        for k in clap_pos:
            self.put("clap", stereo(ins.clap(0.9), 0.0), pos(k))
        for j, k in enumerate(roll):
            v = 0.35 + 0.6 * (j + 1) / len(roll)
            self.put("snare", stereo(ins.snare_roll_hit(v), 0.15 * (-1) ** j), pos(k))
        for k, f in toms:
            self.put("tom", stereo(ins.tom(0.9, f), {196.0: -0.4, 147.0: 0.0, 110.0: 0.4}[f]), pos(k))
        # hats
        vel16 = [0.35, 0.18, 0.75, 0.22]
        for k in range(n16):
            if cfg["hat"] == "8" and k % 4 not in (2, 3):
                continue
            is_off8 = k % 4 == 2
            if cfg["ohat"] and is_off8:
                self.put("ohat", stereo(ins.hat(0.8, open_=True), 0.2), pos(k, 1.0))
                continue
            v = vel16[k % 4] * (0.85 + 0.3 * np.random.default_rng(bar["b"] * 31 + k).random())
            self.put("hat", stereo(ins.hat(v), -0.15), pos(k, 1.0))
        if cfg["shaker"]:
            for k in range(n16):
                v = [0.5, 0.3, 0.65, 0.35][k % 4]
                self.put("shaker", stereo(ins.shaker(v), 0.45), pos(k, 1.0))
        if cfg["perc"]:
            for j, k in enumerate((3, 6, 11, 14)):
                if k < n16:
                    self.put("perc", stereo(ins.data_click(0.7, 1.0 + 0.25 * (j % 2)), 0.6 * (-1) ** j), pos(k, 1.0))

    def logo_hit(self) -> None:
        ec = self.sc["endcard"]
        words = ec["vo"]["words"]
        f = words[0]["start"] if words else ec["start"] // FRAME + 42
        t = f * FRAME
        for m, pan, v in ((57, -0.3, 0.5), (64, 0.3, 0.5), (69, 0.0, 0.6), (76, 0.2, 0.45), (81, -0.2, 0.4), (88, 0.25, 0.25)):
            self.put("logo", stereo(ins.bell(m, nsamp(0.4), v, ring=2.0), pan), t)
        self.put("logo", ins.heartbeat(0.9, double=False), t, 0.9)
        self.put("crash", ins.crash(0.6, 3.0), t, 1.2)
        self.events.append((t / SR, f"logo hit on '{words[0]['text'] if words else '?'}' (frame {f})"))

    # -------------------------------------------------------------- mix
    def duck_curve(self, depth: float, rel: float) -> np.ndarray:
        imp = np.zeros(self.L)
        for k in self.kicks:
            if 0 <= k < self.L:
                imp[k] = 1.0
        a, r = nsamp(0.003), nsamp(rel)
        ker = np.concatenate([np.linspace(0, 1, a, endpoint=False), (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, r))) ])
        from scipy.signal import oaconvolve
        d = np.clip(oaconvolve(imp, ker)[: self.L], 0, 1)
        return 1 - depth * d

    def pad_cutoff(self) -> np.ndarray:
        c = np.full(self.L, 1000.0)
        for sid in GROOVE:
            s = self.sc[sid]
            a, b = CFG[sid]["cut"]
            n = s["end"] - s["start"]
            u = np.arange(n) / n
            c[s["start"]: s["end"]] = np.exp(np.log(a) + (np.log(b) - np.log(a)) * u)
        c[self.sc["endcard"]["end"]:] = CFG["endcard"]["cut"][1]
        lc = np.log(c)
        from scipy.ndimage import uniform_filter1d
        return np.exp(uniform_filter1d(lc, nsamp(0.08)))

    def mix(self) -> np.ndarray:
        st = self.stems
        # pad bus: 24 dB low-pass automation, voice-band dip, chorus, width, low cut
        cut = self.pad_cutoff()
        p = sweep(st["pad"], cut, "lp", q=0.75, block=128)
        p = sweep(p, cut * 1.15, "lp", q=0.6, block=128)
        p = peak(p, 2300, -7.0, 0.7)
        p = peak(p, 1200, -2.5, 1.0)
        p = hp(hp(p, 170), 170)
        p = widen(chorus(p, depth_ms=3.5, rate=0.23, mix=0.45), 1.25)
        st["pad"] = p
        # motif: delay + gentle top
        st["motif"] = st["motif"] + pingpong(st["motif"], 0.375, 0.38, 7, 3800, 400) * 0.22
        st["bell"] = peak(st["bell"] + pingpong(st["bell"], 0.375, 0.42, 8, 3500, 300) * 0.3, 2500, -5, 0.8)
        st["logo"] = peak(st["logo"], 2500, -5, 0.8)
        st["arp"] = st["arp"] + pingpong(st["arp"], 0.25, 0.35, 6, 3000, 400) * 0.25
        st["lead"] = chorus(st["lead"], 5, 0.3, 0.5)
        st["midbass"] = saturate(lp(st["midbass"], 1600), 1.3)
        st["hat"] = lp(hp(st["hat"], 6000), 12500)
        st["ohat"] = lp(st["ohat"], 12000)
        st["perc"] = lp(st["perc"], 12000)
        st["shaker"] = lp(st["shaker"], 11000)
        st["clap"] = peak(st["clap"], 2500, -2, 1.0)
        # sidechain from the kick
        for name, (depth, rel) in SIDECHAIN.items():
            if name in st:
                st[name] = st[name] * self.duck_curve(depth, rel)[:, None]
        # end card: once drums and bass drop out, pull the (no longer pumped) pad and bells down
        ec = self.sc["endcard"]
        t_drop = ec["start"] + self.B(4)
        tg = np.ones(self.L)
        r = nsamp(0.35)
        tg[t_drop:t_drop + r] = np.linspace(1, 0.6, r)
        tg[t_drop + r:] = 0.6
        for name in ("pad", "bell"):
            st[name] = st[name] * tg[:, None]
        self.events.append((t_drop / SR, "end card: drums + bass out"))
        # sends
        dry = np.zeros((self.L, 2))
        hall_in = np.zeros((self.L, 2))
        room_in = np.zeros((self.L, 2))
        dark_in = np.zeros((self.L, 2))
        for name, x in st.items():
            g = GAIN.get(name, 0.0)
            if g == 0:
                print("  (unused stem)", name)
                continue
            x = x * g
            dry += x
            hall_in += x * SEND_HALL.get(name, 0.0)
            room_in += x * SEND_ROOM.get(name, 0.0)
            dark_in += x * SEND_DARK.get(name, 0.0)
        hall = convolve(hp(hall_in, 200), self.irs["hall"])
        hall = peak(hall, 2500, -4, 0.8) * self.duck_curve(*SIDECHAIN["hall"])[:, None]
        room = convolve(room_in, self.irs["room"])
        dark = convolve(dark_in, self.irs["dark"])
        y = dry + hall * 0.9 + room * 0.8 + dark * 0.8
        self.stem_levels = {k: float(db(np.sqrt(np.mean((v * GAIN.get(k, 0)) ** 2)) + 1e-12)) for k, v in st.items()}
        # master
        y = hp(y, 22)
        y = mono_below(y, 110)
        y = compress(y, threshold_db=-20, ratio=1.8, attack=0.015, release=0.2, knee_db=8)
        y = y[: self.N]
        # end: everything faded by the final frame; start: tiny fade-in
        fo = nsamp(1.4)
        y[-fo:] *= (np.cos(np.linspace(0, np.pi / 2, fo)) ** 2)[:, None]
        y = fade(y, 0.02, 0.0)
        # loudness + true-peak limiting (iterate: the limiter shaves a little loudness)
        g = undb(TARGET_LUFS - lufs_integrated(y))
        for _ in range(4):
            out = limiter(y * g, ceiling_db=CEILING_DBTP - 0.3)
            l = lufs_integrated(out)
            if abs(l - TARGET_LUFS) < 0.1:
                break
            g *= undb(TARGET_LUFS - l)
        tp = true_peak(out)
        if db(tp) > CEILING_DBTP:
            out *= undb(CEILING_DBTP) / tp
        out[-1] = 0.0
        return out


def render_music(lang: str) -> tuple[np.ndarray, Song]:
    s = Song(lang)
    s.intro()
    s.impact()
    s.groove()
    y = s.mix()
    assert len(y) == s.N
    write_wav(ROOT / f"public/audio/music.{lang}.wav", y)
    return y, s


def main(argv: list[str]) -> None:
    what = argv[1] if len(argv) > 1 else "all"
    langs = argv[2:] or ["en"]
    if what in ("sfx", "all"):
        import sfx
        rep = sfx.render_all(ROOT / "public/audio/sfx")
        for k, v in rep.items():
            print(f"sfx {k:12s} {v}")
    if what in ("sfx", "all"):
        import analyze
        analyze.sfx_png(ROOT / "out/audio/sfx.png")
    if what in ("music", "all"):
        import analyze
        for lang in langs:
            y, s = render_music(lang)
            analyze.report(lang, y, s)


if __name__ == "__main__":
    main(sys.argv)
