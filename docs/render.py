"""Render a docs/*.html page to a trimmed PNG with headless Chrome.

Chrome screenshots the whole window, so a page shorter than the window leaves a
band of background at the bottom. This renders tall, then trims any uniform
bottom rows, giving an exact-height image regardless of how the page grows.

    python3 docs/render.py architecture.html architecture.png
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DOCS = Path(__file__).resolve().parent
WIDTH = 1680          # CSS px; must match .page width in the HTML
SCALE = 2             # device pixel ratio -> 3360px wide PNG
TALL = 2600           # render taller than the page, then trim
PAD = 34              # bottom padding to keep, in CSS px


def render(src: str, dst: str) -> None:
    out = DOCS / dst
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
         f"--force-device-scale-factor={SCALE}",
         f"--window-size={WIDTH},{TALL}",
         f"--screenshot={out}", (DOCS / src).as_uri()],
        check=True, capture_output=True)

    im = Image.open(out).convert("RGB")
    w, h = im.size
    bg = im.getpixel((w - 4, h - 4))
    row = h
    while row > 1:
        strip = im.crop((0, row - 1, w, row))
        if strip.getcolors(maxcolors=4) != [(w, bg)]:
            break
        row -= 1
    im.crop((0, 0, w, min(h, row + PAD * SCALE))).save(out, optimize=True)
    print(f"{dst}: {w}x{min(h, row + PAD * SCALE)}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
