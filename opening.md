# Your scenes: cold-open (abs 0-299) + problem (abs 300-599)
Files you own: src/scenes/ColdOpen.tsx, src/scenes/cold-open/*, src/scenes/Price.tsx (if present; the € odometer), src/scenes/Problem.tsx, src/dev/cold-open.tsx, src/dev/problem.tsx.
This is the part the owner first called "empty and slow" — it must feel full and alive every frame.
New beats: "Would you buy it blind?" (cold-open, ~frames 227-283): give it a visual idea, e.g. the hero racket dims/blurs or a blindfold-like dark wipe, ending on a strong frame into the cut. "Pure guesswork." (problem, end of the scene): e.g. jargon chips/specs scramble or a dice/guess motif over the card wall; keep it on-brand (black studio, lime accent).
Review findings (v2):
- [major] cold-open 236-299: after the hero lands (~207) and the sweep ends (~247) the hero hangs nearly still until the cut. Now the new line plays here; add continuous motion (slow push/yaw) and the new beat.
- [major] problem 360-411 ("one flat" beat): dim, nearly empty and nearly static for ~0.85 s (hero alone, side rackets fade to black, ~91% of pixels below luminance 30), then one small dim racket / one listing card on black until the card wall at ~414. Make this beat full and bright enough to read: e.g. the "one flat photo" listing card big and centred immediately, with the wall building around it.
- [minor] cold-open 81-101: the € price's dark text-shadow is clipped into hard rectangles by each odometer digit column's overflow:hidden (visible over the light Head macro). Fix the shadow (e.g. put the shadow on a parent, or pad the columns).
- [minor] cold-open 81-101: full-frame macro of the white/red Head racket is soft/mushy at 1440p (low-res texture blown up). Use a sharper source, a smaller crop factor, or a different racket for the macro.
Captions are handled by another builder; ignore caption line breaks.
