# Your scene: finder (abs 2280-2699, 7 s)
Files you own: src/scenes/Finder.tsx, src/dev/finder.tsx, and the finder capture shots/manifests if you re-capture.
New beat: "Your match, in seconds." at the end — land on the result racket with energy (e.g. the 3D racket spins in, name lights up). Do NOT feature the match percentage.
Review findings (v2):
- [major] finder 2310-2520: the results page held ~3.5 s; the Radical Team stayed front-on (never spun) and only a slow push moved; after the voice ended there was no event for ~1.6 s. Now the new line fills the end; add continuous motion (spin the racket / move between result cards / highlight the name).
- [minor, honesty] the results hold showed a large lime "87% match" badge (+ 87%/84% chips) during a push-in, while the page's footnote says match % is computed from sample platform scores. Don't push in on or highlight the %: frame the racket and name, crop or blur the badge.
- [minor, audio] at v2 2301-2313 the results-reveal transition SFX was as loud as the VO word "rackets". Lower that SFX (it's placed in your scene via the Sfx component) so the voice stays on top.
