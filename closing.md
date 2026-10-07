# Your scenes: brands (abs 2700-2999, now 5 s) + endcard (abs 3000-3359, 6 s)
Files you own: src/scenes/Brands.tsx, src/scenes/EndCard.tsx, src/dev/brands.tsx, src/dev/endcard.tsx, and the brands capture (public/capture/brands/*, capture/shots/brands*.mjs) if you re-capture.
New words: "All the top brands, side by side. All in one place, updated every season." ("side by side" -> brands lined up; "updated every season" -> e.g. a "New 2026" season tag / fresh rackets dropping into the grid. Don't state any count.)
Review findings (v2):
- [major] brands 2595-2650: hero brand logos in the 3D ring look soft (tiles are 316x320 JPEG captures in public/capture/brands/tiles/*.jpg scaled ~2.5x to ~800 px at 1440p). Re-capture the tiles at dpr 3 (or use the site's own vector/hi-res logo files if the site has them under the repo's public/ folder) so logos are crisp at 2560x1440.
- [minor] brands 2547-2562: the marquee-to-3D-ring transition plays as a messy double exposure (~0.25 s): translucent tiles overlap and names appear twice. Make it a clean transition.
- Make sure no grid has an empty slot and no unfinished racket appears (the capture hides the 14 unfinished; verify by eye).
- Endcard: keep the clean final frame (Paladex / "See it from every side, before you buy it." / "Find your racket"); it now has 6 s with the line ending ~frame 3196 and a ~2.7 s logo hold to the end: keep subtle continuous motion through the hold (no frozen frame), and end cleanly on 3359.
