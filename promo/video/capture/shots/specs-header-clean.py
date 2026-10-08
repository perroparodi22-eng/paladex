"""Remove the page content that bleeds through the sticky header capture.

The header is translucent: when it was captured at scroll S2 the row "Collection AT10"
(and its separator line) sat behind it and got baked into specs-header. In the scene
the header is layered over a page that scrolls, so that row showed twice (a faded
copy stacked above the real one). The middle of the header holds nothing but the
page background: paint it from the clean stretch next to the nav (dpr 2 px).

    python capture/shots/specs-header-clean.py public/capture/specs/header.jpg
"""
import sys
from PIL import Image

path = sys.argv[1]
im = Image.open(path).convert("RGB")
W, H = im.size  # 3840 x 128 (dpr 2)
src = im.crop((1520, 0, 2120, H))  # css 760..1060: logo and nav end at ~630, bleed starts at ~1070
im.paste(src, (2120, 0))  # css 1060..1360
im.paste(src, (2720, 0))  # css 1360..1660 (the search icon at ~1608..1627 is restored below)
icon = Image.open(path).convert("RGB").crop((3180, 20, 3270, 108))  # css 1590..1635, y 10..54
# restore the search icon from the original capture (it sits in the painted span)
orig_icon = icon
im.paste(orig_icon, (3180, 20))
im.save(path, quality=94)
