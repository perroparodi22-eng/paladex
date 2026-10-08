"""Paladex launch ad: original music bed + sound effects.

    python audio/make_music.py            # sfx + music + checks
    python audio/make_music.py sfx        # only the sound effects
    python audio/make_music.py music en   # only the English music bed (+ checks)

Writes
    public/audio/sfx/<name>.wav           see sfx.SFX (click tick pop swipe whoosh whoosh-soft impact riser
                                          shimmer hit whip rise-short)
    public/audio/music.<lang>.wav         exact length = durationInFrames / 60 s, 48 kHz stereo 16 bit
    out/audio/*                           spectrogram/waveform PNGs, mix checks, stats

Minimal electronic, 120 BPM, A minor, with drive from the first frame (v2):

    cold-open  hard downbeat hit on frame 0, intro groove: four-on-the-floor kick, clap, 16th hats,
               galloping bass, 16th sequencer pulse, chord stabs on the montage grid
    problem    the build: the groove drops behind a closed low-pass that opens over the scene, snare
               roll accelerating (quarters -> 8ths -> 16ths), spec-sheet 'data storm', riser; the last
               beat is a hard stop (silence + reverse suck) right before the drop
    reveal     the drop: impact on frame 0, full groove (pad, motif, stabs, snare layer)
    turn..brands  full groove with a different arrangement per scene (extra percussion layer, arps,
               lead, bass variations) and a different fill into every scene start
    endcard    groove under the logo + line, a one-beat stop after the last word, then a big final hit
               (kick, sub drop, chord, crash, bells) and its tail to the last frame

Everything is placed from src/data/timeline.<lang>.json, so every section change lands exactly on a
scene start (scenes start on the beat grid: 1 beat = 30 frames = 24000 samples).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from functools import lru_cache
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
SWING = int(0.10 * S16)    # late odd 16ths -> slight shuffle

TARGET_LUFS = -15.5
CEILING_DBTP = -1.2

# ------------------------------------------------------------------ harmony

CHORDS = {  # sub root (MIDI), pad voicing (MIDI)
    "Am": dict(root=33, pad=[57, 60, 64, 67, 69]),  # A1 | A3 C4 E4 G4 A4   (Am7)
    "F": dict(root=29, pad=[53, 57, 60, 64, 67]),   # F1 | F3 A3 C4 E4 G4   (Fmaj9)
    "C": dict(root=36, pad=[55, 60, 62, 64, 67]),   # C2 | G3 C4 D4 E4 G4   (Cadd9)
    "G": dict(root=31, pad=[55, 59, 62, 67, 69]),   # G1 | G3 B3 D4 G4 A4   (Gadd9)
    "E": dict(root=28, pad=[52, 56, 59, 62, 64]),   # E1 | E3 G#3 B3 D4 E4  (E7, pulls back to Am)
}
STAB = {  # tighter mid-register voicings for the chord stabs
    "Am": (57, 60, 64, 69, 71),  # A3 C4 E4 A4 B4 (add9)
    "F": (57, 60, 65, 67, 69),   # F/A: A3 C4 F4 G4 A4
    "C": (55, 60, 62, 64, 67),
    "G": (55, 59, 62, 67, 69),
    "E": (56, 59, 62, 64, 68),
}

# The hook: rising three-note figure (3-3-2 feel) and a falling answer. (16th, MIDI, length in 16ths)
MOTIF = {
    "Am": [(0, 69, 2), (3, 72, 2), (6, 76, 3), (10, 74, 2), (12, 72, 4)],
    "F": [(0, 69, 2), (3, 72, 2), (6, 77, 3), (10, 76, 2), (12, 72, 4)],
    "C": [(0, 67, 2), (3, 72, 2), (6, 76, 3), (10, 74, 2), (12, 76, 4)],
    "G": [(0, 67, 2), (3, 71, 2), (6, 74, 3), (10, 76, 2), (12, 74, 4)],
    "E": [(0, 68, 2), (3, 71, 2), (6, 76, 2), (10, 74, 2), (12, 71, 4)],
}

# Chord plan per scene: (cycle, tail). The cycle repeats / is truncated to fill the scene; the tail is
# anchored to the end, so the turnaround into the next scene survives a scene getting a beat longer.
PROG = {
    "cold-open": ([("Am", 4), ("F", 4)], [("G", 2)]),
    "problem": ([("Am", 4), ("F", 4)], [("E", 4)]),
    "reveal": ([("Am", 4), ("C", 4)], [("G", 2)]),
    "turn": ([("Am", 4), ("F", 4), ("C", 4), ("G", 4)], []),
    "specs": ([("F", 4), ("Am", 4)], [("G", 2)]),
    "reviews": ([("C", 4), ("G", 4)], []),
    "pros": ([("Am", 2), ("F", 2), ("C", 2), ("G", 2)], []),
    "finder": ([("Am", 4), ("F", 4), ("C", 4), ("G", 4)], []),
    "brands": ([("F", 4)], [("G", 2), ("E", 2)]),
    "endcard": ([("Am", 4)], [("F", 2), ("G", 2)]),  # then a stop and the final hit on Am (ending())
}
PROG_DEFAULT = ([("Am", 4), ("F", 4), ("C", 4), ("G", 4)], [])

# Per-scene arrangement of the groove scenes (cold-open = intro groove; problem = build and endcard =
# ending are special, see build() / ending()).
#   kick "4" four-on-the-floor | "4+" with a pickup on the 'and' of 4 every other bar
#   snare: snare layered under the clap; ghost: ghost clap/snare 16ths
#   perc: extra percussion layer (rim | bongo | data); bass: BASS_PATTERNS id; pulse: 16th sequencer
#   stab: chord stabs ("drive" on the montage grid | "down" on downbeats); motif: pluck | bell | callresp
#   fill: the fill into the NEXT scene (FILLS); cut: pad low-pass start/end (Hz)
_B = dict(kick="4", clap=True, snare=False, ghost=False, hat="16", ohat=True, shaker=False, tamb=False, perc=None,
          bass=1, pulse=None, stab=None, pad=True, motif="pluck", arp=None, lead=False, fill="roll1", cut=(1500, 2500))
CFG = {
    "cold-open": {**_B, "ohat": False, "bass": 3, "pulse": "A", "stab": "drive", "pad": False, "motif": None,
                  "fill": "roll1", "cut": None},
    "reveal": {**_B, "snare": True, "stab": "down", "fill": "roll2", "cut": (1800, 3200)},
    "turn": {**_B, "ghost": True, "perc": "rim", "arp": "A", "fill": "toms", "cut": (2200, 3400)},
    "specs": {**_B, "ohat": False, "shaker": True, "perc": "data", "bass": 0, "pulse": "B", "motif": "bell",
              "fill": "stutter", "cut": (2000, 2600)},
    "reviews": {**_B, "ghost": True, "tamb": True, "perc": "bongo", "bass": 2, "stab": "down", "motif": "callresp",
                "arp": "B", "fill": "kickdrop", "cut": (2400, 3400)},
    "pros": {**_B, "kick": "4+", "snare": True, "ghost": True, "shaker": True, "perc": "bongo", "bass": 3,
             "pulse": "A", "lead": True, "fill": "roll2", "cut": (2600, 3800)},
    "finder": {**_B, "shaker": True, "perc": "rim", "pulse": "B", "arp": "B", "fill": "riser", "cut": (2200, 4000)},
    "brands": {**_B, "kick": "4+", "snare": True, "ghost": True, "shaker": True, "tamb": True, "perc": "bongo",
               "bass": 2, "pulse": "A", "stab": "drive", "arp": "A", "lead": True, "fill": "big", "cut": (3200, 5000)},
    "endcard": {**_B, "snare": True, "stab": "down", "fill": None, "cut": (3200, 1100)},
}
CFG_DEFAULT = {**_B, "perc": "rim", "arp": "A"}

BASS_PATTERNS = {  # (16th, semitone offset from the mid root)
    0: [(2, 0), (6, 0), (10, 0), (14, 0)],
    1: [(2, 0), (6, 0), (10, 0), (13, 0), (14, 12)],
    2: [(2, 0), (3, 12), (6, 0), (10, 0), (11, 12), (14, 0), (15, 7)],
    3: [(1, 0), (2, 0), (3, 12), (5, 0), (6, 0), (7, 12), (9, 0), (10, 0), (11, 12), (13, 0), (14, 0), (15, 7)],  # gallop
}
PULSE = {"A": [0, 12, 7, 12], "B": [12, 7, 0, 7, 12, 0, 19, 7]}
PERC = {  # (16th, kind/pitch, pan)
    "rim": [(3, 1.0, -0.5), (6, 0.8, 0.5), (10, 1.0, -0.5), (13, 0.85, 0.5)],
    "bongo": [(2, 330.0, -0.45), (3, 220.0, -0.45), (7, 330.0, 0.45), (10, 220.0, 0.45), (11, 330.0, -0.45),
              (14, 247.0, 0.45)],
    "data": [(3, 1.0, 0.6), (6, 1.25, -0.6), (11, 1.0, 0.6), (14, 1.25, -0.6)],
}
# Fills into the next scene: length in beats and which parts drop out under them.
FILLS = {
    "roll1": dict(beats=1, mutes={"clap", "ohat", "ghost"}),
    "roll2": dict(beats=2, mutes={"clap", "ohat", "ghost"}),
    "toms": dict(beats=1, mutes={"clap", "ohat", "ghost", "perc"}),
    "stutter": dict(beats=1, mutes={"clap", "hat", "ohat", "ghost", "perc"}),
    "kickdrop": dict(beats=1, mutes={"kick", "clap", "hat", "ohat", "ghost", "bass", "pulse", "perc", "shaker", "tamb"}),
    "riser": dict(beats=1, mutes={"clap", "ohat", "ghost"}),
    "big": dict(beats=2, mutes={"clap", "ohat", "ghost", "perc"}),
}

# Stem gains (linear) and bus sends.
GAIN = dict(kick=0.52, sub=0.14, midbass=0.21, pad=0.85, clap=0.80, snare=0.40, tom=0.34, hat=0.32, ohat=0.14,
            shaker=0.20, perc=0.30, rim=0.22, bongo=0.25, tamb=0.14, motif=0.58, bell=0.15, arp=0.24, lead=0.11,
            stab=0.55, pulse=0.22, crash=0.08, swell=0.15, riser=0.26, impact=0.62, logo=0.15, suck=0.30,
            downl=0.10)
# Section gain automation (dB) on the pre-master sum: an arc (the drop and the last scenes on top);
# a (from, to) pair ramps across the scene.
SECTION_GAIN = {"cold-open": 0.8, "problem": (-1.6, 0.8), "reveal": 0.6, "turn": 0.0, "specs": 0.0, "reviews": 0.0,
                "pros": -0.2, "finder": 0.0, "brands": 0.0, "endcard": -0.4}
FINAL_BOOST_DB = 1.5  # the final hit and its tail sit a little above the end card groove
SEND_HALL = dict(pad=0.30, motif=0.28, bell=0.55, arp=0.30, lead=0.45, clap=0.10, logo=0.9, stab=0.25, pulse=0.12,
                 swell=0.2, crash=0.2, bongo=0.10, rim=0.15, downl=0.3)
SEND_ROOM = dict(clap=0.30, snare=0.30, tom=0.25, hat=0.10, perc=0.25, shaker=0.08, rim=0.25, bongo=0.25, tamb=0.15)
SEND_DARK = dict(impact=0.55, riser=0.25, stab=0.08)
SIDECHAIN = dict(sub=(0.92, 0.13), midbass=(0.7, 0.16), pad=(0.5, 0.24), arp=(0.25, 0.2), motif=(0.12, 0.18),
                 lead=(0.2, 0.2), stab=(0.25, 0.18), pulse=(0.45, 0.14), hall=(0.3, 0.25))
# the build's closing low-pass applies to these stems (kick, sub and fx stay full range)
FILTER_STEMS = ("hat", "ohat", "clap", "snare", "pulse", "midbass", "perc", "shaker", "tamb", "stab", "rim", "bongo")
GATE_EXEMPT = ("suck",)


# ------------------------------------------------------------------ cached voices (identical notes repeat)

def _cache(fn):
    return lru_cache(maxsize=None)(fn)


kick_c = _cache(lambda v, long=False: ins.kick(v, long))
sub_c = _cache(lambda m, n, v: ins.sub(m, n, v))
midbass_c = _cache(lambda m, n, v: ins.midbass(m, n, v))
pad_c = _cache(lambda midis, n, a, r: ins.pad_chord(list(midis), n, attack=a, release=r))
stab_c = _cache(lambda midis, dur, v, bright, rel: ins.stab(midis, dur, v, bright, rel))
pulse_c = _cache(lambda m, n, v, bright: ins.pulse(m, n, v, bright))
pluck_c = _cache(lambda m, n, v, bright: ins.pluck(m, n, v, bright))
glass_c = _cache(lambda m, n, v: ins.glass(m, n, v))
bell_c = _cache(lambda m, n, v, ring=1.4: ins.bell(m, n, v, ring=ring))
lead_c = _cache(lambda m, n, v: ins.lead(m, n, v))
clap_c = _cache(lambda v: ins.clap(v))
snare_c = _cache(lambda v: ins.snare(v))


def r2(v: float) -> float:
    return round(float(v), 2)


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
            self.sc[s["id"]] = dict(id=s["id"], f0=s["start"], b0=s["start"] // 30, beats=s["duration"] // 30,
                                    start=s["start"] * FRAME, end=(s["start"] + s["duration"]) * FRAME, vo=s.get("vo"))
        self.stems: dict[str, np.ndarray] = defaultdict(lambda: np.zeros((self.L, 2)))
        self.kicks: list[int] = []
        self.irs = dict(
            hall=make_ir(2.8, predelay=0.025, damp_hz=7000, lo_cut=220, decay_hz_end=1600, seed=101),
            room=make_ir(0.6, predelay=0.006, damp_hz=8000, lo_cut=300, decay_hz_end=2500, seed=102),
            dark=make_ir(4.0, predelay=0.03, damp_hz=3000, lo_cut=60, decay_hz_end=600, seed=103),
        )
        self.events: list[tuple[float, str]] = []  # (seconds, label) for the report
        self.stops: list[tuple[int, int]] = []     # hard stops (sample ranges of silence before a hit)
        self.filters: list[tuple[int, int, np.ndarray]] = []  # (a, b, cutoff curve) on FILTER_STEMS
        self.t_final: int | None = None                       # sample of the final hit
        # roles: the scene before the drop builds, the drop scene hits, the last scene ends
        self.drop = "reveal" if "reveal" in self.sc else None
        i = self.order.index(self.drop) if self.drop else -1
        self.build_id = self.order[i - 1] if i > 0 else None
        self.end_id = self.order[-1]

    # -------------------------------------------------------------- helpers
    @staticmethod
    def B(beat: float) -> int:
        return int(round(beat * SPB))

    @staticmethod
    def P(step: int, swing: float = 1.0) -> int:
        """Sample position of an absolute 16th step (odd 16ths swung late)."""
        return step * S16 + (int(SWING * swing) if step % 2 else 0)

    def put(self, stem: str, x: np.ndarray, at: int, gain: float = 1.0) -> None:
        add_at(self.stems[stem], stereo(x) if x.ndim == 1 else x, at, gain)

    def ev(self, t: int, label: str) -> None:
        self.events.append((t / SR, label))

    def segments(self, sid: str, beats: int | None = None) -> list[dict]:
        s = self.sc[sid]
        beats = s["beats"] if beats is None else beats
        cycle, tail = PROG.get(sid, PROG_DEFAULT)
        tail = list(tail)
        tb = sum(nb for _, nb in tail)
        if tb >= beats:
            tail, tb = [], 0
        head, tot, i = [], 0, 0
        while tot < beats - tb:
            c, nb = cycle[i % len(cycle)]
            nb = min(nb, beats - tb - tot)
            head.append((c, nb))
            tot += nb
            i += 1
        out, b = [], s["b0"]
        for j, (c, nb) in enumerate(head + tail):
            out.append(dict(scene=sid, i=j, b=b, beats=nb, chord=c, last=False))
            b += nb
        out[-1]["last"] = True
        return out

    def next_scene(self, sid: str) -> str | None:
        i = self.order.index(sid)
        return self.order[i + 1] if i + 1 < len(self.order) else None

    # -------------------------------------------------------------- arrangement
    def arrange(self) -> None:
        for sid in self.order:
            if sid == self.build_id:
                self.build(sid)
            elif sid == self.end_id:
                self.ending(sid)
            else:
                self.groove_scene(sid)
            self.downbeat(sid)
        self.logo_hit()

    def downbeat(self, sid: str) -> None:
        """The accent on every scene's frame 0."""
        t = self.sc[sid]["start"]
        if sid == self.order[0]:
            # open hard: no fade-in, a hit on the very first sample
            self.put("impact", ins.sub_drop(0.9, 78, 36), t, 0.5)
            self.put("crash", ins.crash(1.0, 2.4), t, 1.5)
            self.put("stab", stab_c(STAB["Am"], 0.32, 1.0, 1.0, 0.4), t, 1.15)
            self.ev(t, f"{sid}: hard downbeat hit on frame 0, intro groove")
        elif sid == self.drop:
            self.put("impact", kick_c(1.0, True), t, 1.0)
            self.put("impact", ins.sub_drop(1.8, 85, 31), t, 0.8)
            self.put("impact", ins.boom(1.2), t, 0.35)
            self.put("crash", ins.crash(1.0, 3.0), t, 2.2)
            self.put("stab", stab_c(STAB["Am"], 0.45, 1.0, 1.0, 0.8), t, 1.3)
            self.put("downl", ins.downlifter(1.6), t, 1.0)
            self.kicks.append(t)
            self.ev(t, f"{sid}: DROP (impact on frame 0)")
        elif sid == self.build_id:
            self.put("crash", ins.crash(0.8), t, 1.0)
            self.put("downl", ins.downlifter(1.0, 7000, 300), t, 0.8)
        elif sid == self.end_id:
            self.put("crash", ins.crash(1.0, 2.6), t, 1.4)
            self.put("impact", ins.sub_drop(0.8, 80, 40), t, 0.35)
        else:
            self.put("crash", ins.crash(0.85), t, 1.0)

    # -------------------------------------------------------------- groove scenes
    def groove_scene(self, sid: str) -> None:
        cfg = CFG.get(sid, CFG_DEFAULT)
        s = self.sc[sid]
        nxt = self.next_scene(sid)
        fill = None
        if nxt and cfg["fill"] and nxt != self.drop:
            kind = cfg["fill"]
            fb = min(FILLS[kind]["beats"], max(1, s["beats"] - 2))
            fill = dict(kind=kind, beats=fb, frm=(s["b0"] + s["beats"] - fb) * 4, mutes=FILLS[kind]["mutes"])
        segs = self.segments(sid)
        for seg in segs:
            self.render_seg(sid, cfg, seg, fill, skip_k0=(sid == self.drop and seg["i"] == 0))
        if fill:
            self.render_fill(sid, fill)
        self.ev(s["start"], f"{sid}: {' '.join(sg['chord'] + ('' if sg['beats'] == 4 else str(sg['beats'])) for sg in segs)}"
                + (f" | fill '{fill['kind']}'" if fill else ""))

    def render_seg(self, sid: str, cfg: dict, seg: dict, fill: dict | None, skip_k0: bool = False) -> None:
        b, nb = seg["b"], seg["beats"]
        n16 = nb * 4
        s0 = b * 4
        t0 = self.B(b)
        chord = CHORDS[seg["chord"]]
        P = self.P

        def on(part: str, k: int) -> bool:
            return not (fill is not None and s0 + k >= fill["frm"] and part in fill["mutes"])

        # ---- pad
        if cfg["pad"]:
            attack = 0.02 if (sid == self.drop and seg["i"] == 0) else 0.12
            self.put("pad", pad_c(tuple(chord["pad"]), nb * SPB, attack, 0.7), t0)

        # ---- chord stabs
        if cfg["stab"]:
            ks = [0] if cfg["stab"] == "down" else [k for k in (0, 6, 10) if k < n16]
            for k in ks:
                if k == 0 and t0 == self.sc[sid]["start"] and sid in (self.drop, self.order[0]):
                    continue  # the downbeat hit carries its own (longer) stab
                dur = 0.3 if cfg["stab"] == "down" else (0.16 if k else 0.22)
                self.put("stab", stab_c(STAB[seg["chord"]], dur, 1.0 if k == 0 else 0.8, 0.9, 0.2), P(s0 + k, 0.5))

        # ---- motif / bells / lead
        notes = MOTIF[seg["chord"]]
        mode = cfg["motif"]
        if mode == "callresp":
            mode = "bell" if seg["i"] % 2 == 0 else "pluck"
        if mode == "bell":
            for k, m, ln in notes:
                if k in (0, 6, 12) and k < n16:
                    self.put("bell", stereo(bell_c(m, ln * S16, 0.9), -0.1 if k == 6 else 0.12), P(s0 + k))
        elif mode == "pluck":
            for j, (k, m, ln) in enumerate(notes):
                if k >= n16:
                    continue
                v = 1.0 if j in (0, 2) else 0.82
                self.put("motif", pluck_c(m, ln * S16, v, 0.85 if sid == self.drop else 1.0), P(s0 + k))
                if cfg["lead"]:
                    self.put("lead", lead_c(m + 12, ln * S16, v), P(s0 + k))

        # ---- arp
        if cfg["arp"]:
            tones = [m + 12 for m in chord["pad"]]
            seq = [0, 1, 2, 3, 4, 3, 2, 1] if cfg["arp"] == "A" else [0, 2, 1, 3, 2, 4, 3, 1]
            for k in range(n16):
                m = tones[seq[k % 8]]
                v = 0.9 if k % 4 == 0 else 0.55 + 0.1 * (k % 2)
                pan = 0.55 * np.sin(2 * np.pi * (k / 16 + b / 8))
                self.put("arp", stereo(glass_c(m, int(S16 * 0.9), r2(v)), float(pan)), P(s0 + k, 0.5))

        # ---- bass: pumping sub + mid pattern
        sub_end = self.B(b + nb)
        if fill is not None and "bass" in fill["mutes"]:
            sub_end = min(sub_end, fill["frm"] * S16)
        if sub_end > t0:
            self.put("sub", sub_c(chord["root"], sub_end - t0, 1.0), t0)
        mid_root = chord["root"] + 12
        gallop = cfg["bass"] == 3
        for k, off in BASS_PATTERNS[cfg["bass"]]:
            if k < n16 and on("bass", k):
                v = 0.95 if off == 0 else 0.72
                ln = int(S16 * (0.85 if gallop else 1.6))
                self.put("midbass", midbass_c(mid_root + off, ln, v), P(s0 + k, 0.5))

        # ---- 16th sequencer pulse
        if cfg["pulse"]:
            pat = PULSE[cfg["pulse"]]
            base = chord["root"] + 24
            for k in range(n16):
                if not on("pulse", k):
                    continue
                st = s0 + k
                v = [1.0, 0.55, 0.75, 0.6][k % 4]
                bright = 0.55 + 0.4 * (0.5 - 0.5 * np.cos(2 * np.pi * st / 64))
                pan = 0.25 * (-1) ** k
                self.put("pulse", stereo(pulse_c(base + pat[st % len(pat)], int(S16 * 0.8), v, r2(bright)), pan),
                         P(st, 0.5))

        # ---- drums
        kicks = list(range(0, n16, 4))
        if cfg["kick"] == "4+" and n16 >= 16 and seg["i"] % 2 == 1:
            kicks.append(14)
        for k in kicks:
            if (k == 0 and skip_k0) or not on("kick", k):
                continue
            v = 1.0 if k % 16 == 0 else (0.93 if k % 4 == 0 else 0.72)
            self.put("kick", kick_c(v), P(s0 + k))
            self.kicks.append(P(s0 + k))
        for k in (4, 12):
            if k < n16 and on("clap", k):
                self.put("clap", stereo(clap_c(0.9)), P(s0 + k))
                if cfg["snare"]:
                    self.put("snare", stereo(snare_c(0.85)), P(s0 + k))
        if cfg["ghost"]:
            for k, v in ((7, 0.32), (15, 0.25)):
                if k < n16 and on("ghost", k):
                    self.put("snare", stereo(snare_c(v), 0.2), P(s0 + k))
        vel16 = [0.35, 0.18, 0.75, 0.22]
        for k in range(n16):
            if cfg["hat"] == "8" and k % 4 not in (2, 3):
                continue
            if cfg["ohat"] and k % 4 == 2:
                if on("ohat", k):
                    self.put("ohat", stereo(ins.hat(0.8, open_=True), 0.2), P(s0 + k))
                continue
            if not on("hat", k):
                continue
            v = vel16[k % 4] * (0.85 + 0.3 * np.random.default_rng(b * 31 + k).random())
            self.put("hat", stereo(ins.hat(v), -0.15), P(s0 + k))
        if cfg["shaker"]:
            for k in range(n16):
                if on("shaker", k):
                    self.put("shaker", stereo(ins.shaker([0.5, 0.3, 0.65, 0.35][k % 4]), 0.45), P(s0 + k))
        if cfg["tamb"]:
            for k in range(n16):
                if k % 4 in (2, 3) and on("tamb", k):
                    self.put("tamb", stereo(ins.tamb(0.85 if k % 4 == 2 else 0.35), -0.4), P(s0 + k))
        if cfg["perc"]:
            for j, (k, a, pan) in enumerate(PERC[cfg["perc"]]):
                if k >= n16 or not on("perc", k):
                    continue
                if cfg["perc"] == "rim":
                    self.put("rim", stereo(ins.rim(0.8, a), pan), P(s0 + k))
                elif cfg["perc"] == "bongo":
                    self.put("bongo", stereo(ins.bongo(0.9 if a < 300 else 0.7, a), pan), P(s0 + k))
                else:
                    self.put("perc", stereo(ins.data_click(0.7, a), pan), P(s0 + k))

    def render_fill(self, sid: str, fill: dict) -> None:
        """The fill in the last beat(s) of `sid`, landing on the next scene's frame 0."""
        kind, st = fill["kind"], fill["frm"]
        t_end = self.sc[sid]["end"]
        P = self.P
        swell = 0.5
        if kind == "roll1":
            for j in range(4):
                self.put("snare", stereo(ins.snare_roll_hit(0.45 + 0.18 * j), 0.15 * (-1) ** j), P(st + j))
        elif kind == "roll2":
            steps = [0, 2, 4, 5, 6, 7] if fill["beats"] == 2 else [0, 1, 2, 3]
            for j, k in enumerate(steps):
                self.put("snare", stereo(ins.snare_roll_hit(0.35 + 0.65 * (j + 1) / len(steps)), 0.15 * (-1) ** j),
                         P(st + k))
            swell = 0.5 * fill["beats"]
        elif kind == "toms":
            for j, (f, pan) in enumerate(((220.0, -0.45), (165.0, -0.15), (123.0, 0.15), (98.0, 0.45))):
                self.put("tom", stereo(ins.tom(0.8 + 0.07 * j, f), pan), P(st + j))
        elif kind == "stutter":
            for j in range(8):
                self.put("clap", stereo(clap_c(r2(0.3 + 0.09 * j)), 0.2 * (-1) ** j), st * S16 + j * S16 // 2)
        elif kind == "kickdrop":
            rn = self.B(1)
            self.put("riser", ins.noise_riser(rn, 700, 11000, 1.2, 1.6), t_end - rn, 0.9)
            self.put("snare", stereo(ins.snare_roll_hit(0.9)), P(st + 3))
            swell = 0.0
        elif kind == "riser":
            rn = self.B(4)
            self.put("riser", ins.noise_riser(rn, 500, 9000, 1.0, 2.2), t_end - rn, 0.7)
            for j in range(4):
                self.put("snare", stereo(ins.snare_roll_hit(0.5 + 0.16 * j), 0.15 * (-1) ** j), P(st + j))
        elif kind == "big":
            for j, (f, pan) in enumerate(((220.0, -0.45), (196.0, -0.2), (147.0, 0.2), (110.0, 0.45))):
                self.put("tom", stereo(ins.tom(0.85, f), pan), P(st + j))
            for j in range(4):
                self.put("snare", stereo(ins.snare_roll_hit(0.55 + 0.15 * j), 0.15 * (-1) ** j), P(st + 4 + j))
            rn = self.B(2)
            self.put("riser", ins.noise_riser(rn, 400, 10000, 1.1, 2.0), t_end - rn, 0.8)
            swell = 1.0
        if swell:
            self.put("swell", ins.reverse_swell(swell, self.irs["hall"]), t_end - nsamp(swell))

    # -------------------------------------------------------------- the build (scene before the drop)
    def build(self, sid: str) -> None:
        s = self.sc[sid]
        b0, nb = s["b0"], s["beats"]
        stop_b = b0 + nb - 1                      # the last beat is a hard stop
        t_stop, t_end = self.B(stop_b), s["end"]
        P = self.P
        for seg in self.segments(sid):
            chord = CHORDS[seg["chord"]]
            t0 = self.B(seg["b"])
            sub_end = min(self.B(seg["b"] + seg["beats"]), t_stop)
            if sub_end > t0:
                self.put("sub", sub_c(chord["root"], sub_end - t0, 1.0), t0)
            mid_root = chord["root"] + 12
            s0 = seg["b"] * 4
            for k in range(seg["beats"] * 4):
                st = s0 + k
                if st >= stop_b * 4:
                    break
                lb = (st - b0 * 4) / 4                    # local beat
                u = lb / max(1, nb - 1)                    # 0 -> 1 towards the stop
                if k % 4 == 0:
                    self.put("kick", kick_c(1.0 if k % 16 == 0 else 0.93), P(st))
                    self.kicks.append(P(st))
                if k % 16 in (4, 12) and u < 0.4:
                    self.put("clap", stereo(clap_c(0.9)), P(st))
                if k % 4 == 2 and u >= 0.3:
                    self.put("ohat", stereo(ins.hat(0.6 + 0.3 * u, open_=True), 0.2), P(st))
                else:
                    v = [0.35, 0.18, 0.75, 0.22][k % 4] * (0.8 + 0.5 * u)
                    self.put("hat", stereo(ins.hat(v), -0.15), P(st))
                for kk, off in BASS_PATTERNS[3]:
                    if kk == k % 16:
                        self.put("midbass", midbass_c(mid_root + off, int(S16 * 0.85), 0.95 if off == 0 else 0.72),
                                 P(st, 0.5))
                pat = PULSE["A"]
                v = [1.0, 0.55, 0.75, 0.6][k % 4]
                self.put("pulse", stereo(pulse_c(chord["root"] + 24 + pat[st % 4], int(S16 * 0.8), v,
                                                 r2(0.4 + 0.6 * u)), 0.25 * (-1) ** k), P(st, 0.5))
        # snare roll accelerating towards the stop: quarters, 8ths, 16ths
        for st in range(b0 * 4, stop_b * 4):
            rb = (stop_b * 4 - st) / 4               # beats left before the stop
            every = 1 if rb <= 1 else 2 if rb <= 3 else 4 if rb <= 7 else 0
            if every and st % every == 0:
                prog = 1 - rb / 8
                self.put("snare", stereo(ins.snare_roll_hit(0.3 + 0.7 * prog), 0.12 * (-1) ** st), P(st))
        # the spec-sheet 'data storm': random 16th data clicks, denser towards the stop
        rng = np.random.default_rng(77)
        for st in range(b0 * 4 + max(4, (nb - 6) * 4), stop_b * 4):
            u = (st - b0 * 4) / ((nb - 1) * 4)
            if rng.random() < 0.25 + 0.7 * u:
                self.put("perc", stereo(ins.data_click(0.5 + 0.4 * u, float(rng.choice([1.0, 1.25, 1.5]))),
                                        float(rng.uniform(-0.8, 0.8))), P(st))
        # risers into the stop (they end abruptly on it)
        rb = min(6, nb - 1)
        rn = self.B(rb)
        r = ins.noise_riser(rn, 300, 10000, 1.3, 2.0) * 0.9 + ins.pitch_riser(rn, 45, 2.5) * 0.6
        self.put("riser", fade(r, 0.02, 0.004), t_stop - rn)
        # the stop: silence for one beat, then a reverse 'suck' into the drop
        self.stops.append((t_stop, t_end))
        sl = min(nsamp(0.45), t_end - t_stop)
        self.put("suck", ins.suck(sl / SR, self.irs["dark"]), t_end - sl)
        # closing low-pass that opens across the scene (kick + sub stay full range)
        a = s["start"]
        u = np.arange(t_stop - a) / SPB
        pts = [0, (nb - 1) / 3, 2 * (nb - 1) / 3, nb - 1]
        cut = np.exp(np.interp(u, pts, np.log([900.0, 1900.0, 4800.0, 16000.0])))
        self.filters.append((a, t_stop, cut))
        self.ev(s["start"], f"{sid}: build (low-pass 900 Hz -> 16 kHz, snare roll, data storm) "
                + " ".join(sg["chord"] for sg in self.segments(sid)))
        self.ev(t_stop - rn, "riser starts")
        self.ev(t_stop, "hard stop (1 beat) + suck")

    # -------------------------------------------------------------- the ending
    def ending(self, sid: str) -> None:
        s = self.sc[sid]
        b0, nb = s["b0"], s["beats"]
        vo = s["vo"]
        se = (vo["speechEnd"] - s["f0"]) / 30 if vo else nb - 3
        hit_lb = int(np.clip(np.ceil(se - 1e-6), 3, nb - 2))   # first beat after the last word, >= 1 s of tail
        stop_lb = hit_lb - 1
        cfg = CFG.get(sid, CFG_DEFAULT)
        segs = self.segments(sid, beats=stop_lb)
        for seg in segs:
            self.render_seg(sid, cfg, seg, None)
        t_stop, t_hit = self.B(b0 + stop_lb), self.B(b0 + hit_lb)
        self.stops.append((t_stop, t_hit))
        sl = min(nsamp(0.45), t_hit - t_stop)
        self.put("suck", ins.suck(sl / SR, self.irs["dark"]), t_hit - sl, 0.9)
        self.final_hit(t_hit)
        self.ev(s["start"], f"{sid}: {' '.join(sg['chord'] for sg in segs)} groove")
        self.ev(t_stop, "end card: stop (1 beat) + suck")
        self.ev(t_hit, f"FINAL HIT (scene frame {hit_lb * 30}, first beat after the last word)")

    def final_hit(self, t: int) -> None:
        self.t_final = t
        self.put("impact", kick_c(1.0, True), t, 1.0)
        self.put("impact", ins.sub_drop(2.2, 80, 32), t, 0.85)
        self.put("impact", ins.boom(1.4), t, 0.4)
        self.put("crash", ins.crash(1.0, 3.0), t, 2.4)
        self.put("stab", stab_c(STAB["Am"] + (76,), 0.6, 1.0, 0.8, 1.2), t, 1.3)
        self.put("pad", pad_c(tuple(CHORDS["Am"]["pad"]), nsamp(0.5), 0.004, 1.6), t, 1.1)
        for m, pan, v in ((57, -0.3, 0.5), (64, 0.3, 0.5), (69, 0.0, 0.6), (71, -0.15, 0.35), (76, 0.2, 0.45),
                          (81, -0.2, 0.35)):
            self.put("logo", stereo(bell_c(m, nsamp(0.5), v, 1.8), pan), t)
        self.put("downl", ins.downlifter(1.4), t, 0.7)
        self.kicks.append(t)

    def logo_hit(self) -> None:
        ec = self.sc[self.end_id]
        words = ec["vo"]["words"] if ec["vo"] else []
        f = words[0]["start"] if words else ec["f0"] + 30
        t = f * FRAME
        for m, pan, v in ((57, -0.3, 0.5), (64, 0.3, 0.5), (69, 0.0, 0.6), (76, 0.2, 0.45), (81, -0.2, 0.4), (88, 0.25, 0.25)):
            self.put("logo", stereo(bell_c(m, nsamp(0.4), v, 2.0), pan), t)
        self.ev(t, f"logo chime on '{words[0]['text'] if words else '?'}' (frame {f})")

    # -------------------------------------------------------------- mix
    def duck_curve(self, depth: float, rel: float) -> np.ndarray:
        imp = np.zeros(self.L)
        for k in self.kicks:
            if 0 <= k < self.L:
                imp[k] = 1.0
        a, r = nsamp(0.003), nsamp(rel)
        ker = np.concatenate([np.linspace(0, 1, a, endpoint=False), (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, r)))])
        from scipy.signal import oaconvolve
        d = np.clip(oaconvolve(imp, ker)[: self.L], 0, 1)
        return 1 - depth * d

    def pad_cutoff(self) -> np.ndarray:
        c = np.full(self.L, 1000.0)
        for sid in self.order:
            cut = CFG.get(sid, CFG_DEFAULT)["cut"] if sid != self.build_id else None
            if not cut:
                continue
            s = self.sc[sid]
            a, b = cut
            n = s["end"] - s["start"]
            u = np.arange(n) / n
            c[s["start"]: s["end"]] = np.exp(np.log(a) + (np.log(b) - np.log(a)) * u)
        last = CFG.get(self.end_id, CFG_DEFAULT)["cut"]
        if last:
            c[self.sc[self.end_id]["end"]:] = last[1]
        from scipy.ndimage import uniform_filter1d
        return np.exp(uniform_filter1d(np.log(c), nsamp(0.08)))

    @staticmethod
    def filter_region(x: np.ndarray, a: int, b: int, cut: np.ndarray) -> np.ndarray:
        """24 dB resonant low-pass following `cut` over [a, b), crossfaded in/out."""
        pre, xf = nsamp(0.08), nsamp(0.012)
        a0 = max(0, a - pre)
        c = np.concatenate([np.full(a - a0, cut[0]), cut])
        seg = sweep(x[a0:b], c, "lp", q=0.9, block=64)
        seg = sweep(seg, c * 1.1, "lp", q=0.6, block=64)
        w = np.ones(b - a0)
        w[: a - a0] = 0
        w[a - a0: a - a0 + xf] = np.linspace(0, 1, xf)
        w[-xf:] = np.minimum(w[-xf:], np.linspace(1, 0, xf))
        y = x.copy()
        y[a0:b] = x[a0:b] * (1 - w)[:, None] + seg * w[:, None]
        return y

    def section_gain(self) -> np.ndarray:
        g = np.zeros(self.L)
        for sid in self.order:
            s = self.sc[sid]
            v = SECTION_GAIN.get(sid, 0.0)
            a, b = s["start"], s["end"]
            g[a:b] = np.linspace(v[0], v[1], b - a) if isinstance(v, tuple) else v
        last = SECTION_GAIN.get(self.end_id, 0.0)
        g[self.sc[self.end_id]["end"]:] = last[1] if isinstance(last, tuple) else last
        if self.t_final is not None:
            g[self.t_final:] += FINAL_BOOST_DB
        # ~4 ms ramp that starts AT each scene start (causal), so the new level lands on frame 0
        k = nsamp(0.004)
        from scipy.signal import lfilter
        g = lfilter(np.ones(k) / k, [1.0], g)
        return 10 ** (g / 20)

    def stop_gates(self) -> tuple[np.ndarray, np.ndarray]:
        """dry gate (hard stop, instant reopen on the hit) and wet gate (also kills old reverb tails,
        reopening over 150 ms after the hit)."""
        gd, gw = np.ones(self.L), np.ones(self.L)
        f, r = nsamp(0.006), nsamp(0.15)
        for a, b in self.stops:
            for g in (gd, gw):
                g[a:a + f] = np.minimum(g[a:a + f], np.linspace(1, 0, f))
                g[a + f:b] = 0
            gw[b:b + r] = np.minimum(gw[b:b + r], np.linspace(0, 1, r))
        return gd, gw

    def mix(self) -> np.ndarray:
        st = self.stems
        # the build's closing low-pass
        for a, b, cut in self.filters:
            for name in FILTER_STEMS:
                if name in st:
                    st[name] = self.filter_region(st[name], a, b, cut)
        # pad bus: 24 dB low-pass automation, voice-band dip, chorus, width, low cut
        cut = self.pad_cutoff()
        p = sweep(st["pad"], cut, "lp", q=0.75, block=128)
        p = sweep(p, cut * 1.15, "lp", q=0.6, block=128)
        p = peak(p, 2300, -7.0, 0.7)
        p = peak(p, 1200, -2.5, 1.0)
        p = hp(hp(p, 170), 170)
        p = widen(chorus(p, depth_ms=3.5, rate=0.23, mix=0.45), 1.25)
        st["pad"] = p
        # melodic parts: leave room for the voice (2-3 kHz), delays for width and movement
        for name in ("motif", "arp", "lead", "stab", "pulse"):
            st[name] = peak(st[name], 2600, -3.0, 0.9)
        st["motif"] = st["motif"] + pingpong(st["motif"], 0.375, 0.38, 7, 3800, 400) * 0.22
        st["bell"] = peak(st["bell"] + pingpong(st["bell"], 0.375, 0.42, 8, 3500, 300) * 0.3, 2500, -5, 0.8)
        st["logo"] = peak(st["logo"], 2500, -5, 0.8)
        st["arp"] = st["arp"] + pingpong(st["arp"], 0.25, 0.35, 6, 3000, 400) * 0.25
        st["pulse"] = st["pulse"] + pingpong(st["pulse"], 0.375, 0.3, 4, 3200, 500) * 0.2
        st["stab"] = widen(hp(st["stab"], 160), 1.2)
        st["lead"] = chorus(st["lead"], 5, 0.3, 0.5)
        st["midbass"] = saturate(lp(st["midbass"], 2600), 1.7)
        st["hat"] = lp(hp(st["hat"], 6000), 12500)
        st["ohat"] = lp(st["ohat"], 12000)
        st["perc"] = lp(st["perc"], 12000)
        st["shaker"] = lp(st["shaker"], 11000)
        st["tamb"] = lp(st["tamb"], 12500)
        st["clap"] = peak(st["clap"], 2500, -2, 1.0)
        # sidechain from the kick
        for name, (depth, rel) in SIDECHAIN.items():
            if name in st:
                st[name] = st[name] * self.duck_curve(depth, rel)[:, None]
        # hard stops (dry, before the sends)
        gd, gw = self.stop_gates()
        for name in list(st):
            if name not in GATE_EXEMPT:
                st[name] = st[name] * gd[:, None]
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
        y = dry + (hall * 0.9 + room * 0.8 + dark * 0.8) * gw[:, None]
        self.stem_levels = {k: float(db(np.sqrt(np.mean((v * GAIN.get(k, 0)) ** 2)) + 1e-12)) for k, v in st.items()}
        y = y * self.section_gain()[:, None]
        # master: low cut, mono lows, gentle glue
        y = hp(y, 22)
        y = mono_below(y, 110)
        # predictable level into a gentle glue compressor (slow-ish attack keeps the kick transients)
        y = y * undb(-20.0 - lufs_integrated(y[: self.N]))
        y = compress(y, threshold_db=-16, ratio=1.6, attack=0.02, release=0.12, knee_db=8)
        y = y[: self.N]
        # end: the final hit's tail fades to silence by the last frame; start: no fade (hit on sample 0)
        fo = nsamp(0.6)
        y[-fo:] *= (np.cos(np.linspace(0, np.pi / 2, fo)) ** 2)[:, None]
        y = fade(y, 0.0005, 0.0)
        # loudness + true-peak limiting (iterate: the limiter shaves a little loudness)
        g = undb(TARGET_LUFS - lufs_integrated(y))
        for _ in range(5):
            out = limiter(y * g, ceiling_db=CEILING_DBTP - 0.3)
            l = lufs_integrated(out)
            if abs(l - TARGET_LUFS) < 0.08:
                break
            g *= undb(TARGET_LUFS - l)
        tp = true_peak(out)
        if db(tp) > CEILING_DBTP:
            out *= undb(CEILING_DBTP) / tp
        out[-1] = 0.0
        return out


def render_music(lang: str) -> tuple[np.ndarray, Song]:
    s = Song(lang)
    s.arrange()
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
        import analyze
        analyze.sfx_png(ROOT / "out/audio/sfx.png")
    if what in ("music", "all"):
        import analyze
        for lang in langs:
            y, s = render_music(lang)
            analyze.report(lang, y, s)


if __name__ == "__main__":
    main(sys.argv)
