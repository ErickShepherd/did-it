#!/usr/bin/env python3
"""Typeset a wordmark as true-vector glyph OUTLINES (fontTools — no runtime font dependency) and
compose horizontal lockups with a mark SVG. Emits, from --out-prefix P:
  P-wordmark.svg / P-wordmark-white.svg   — the word alone (field ink / structure ink)
  P-lockup.svg   / P-lockup-dark.svg      — mark + word; -dark recolours ONLY the word to structure
                                            ink (the colour mark reads on both light and dark themes)

Deps: fonttools.  Usage:
  build_lockup.py --text excubitor --font sora-600.ttf --mark excubitor.svg \
                  --field '#2E3A4E' --structure '#F4F1E8' --out-prefix excubitor
"""
import argparse, re
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen

ap = argparse.ArgumentParser()
ap.add_argument("--text", required=True); ap.add_argument("--font", required=True)
ap.add_argument("--mark", required=True, help="the full-colour mark SVG to sit left of the word")
ap.add_argument("--field", required=True); ap.add_argument("--structure", required=True)
ap.add_argument("--out-prefix", required=True)
ap.add_argument("--track", type=int, default=12, help="letter-spacing, font units")
ap.add_argument("--word-cap-frac", type=float, default=0.50, help="word cap-height as fraction of mark height")
a = ap.parse_args()

f = TTFont(a.font)
cmap = f.getBestCmap(); gs = f.getGlyphSet(); hmtx = f["hmtx"]
CAP = getattr(f.get("OS/2"), "sCapHeight", 0) or int(0.7 * f["head"].unitsPerEm)

# lay out glyphs; collect outline paths + a tight ink bbox
paths, x = [], 0
xmin = ymin = 1e9; xmax = ymax = -1e9
for ch in a.text:
    gname = cmap.get(ord(ch))
    if gname is None:
        raise SystemExit(f"font has no glyph for {ch!r}")
    pen = SVGPathPen(gs); gs[gname].draw(pen); d = pen.getCommands()
    if d:
        paths.append(f'<path transform="translate({x},0)" d="{d}"/>')
        bp = BoundsPen(gs); gs[gname].draw(bp)
        if bp.bounds:
            gx0, gy0, gx1, gy1 = bp.bounds
            xmin, ymin = min(xmin, x + gx0), min(ymin, gy0)
            xmax, ymax = max(xmax, x + gx1), max(ymax, gy1)
    x += hmtx[gname][0] + a.track
WW, WH = xmax - xmin, ymax - ymin
word = f'<g transform="translate({-xmin},{ymax}) scale(1,-1)">{"".join(paths)}</g>'


def svgdoc(wpx, hpx, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{wpx:.0f}" height="{hpx:.0f}" '
            f'viewBox="0 0 {wpx:.0f} {hpx:.0f}">{body}</svg>\n')


open(f"{a.out_prefix}-wordmark.svg", "w").write(svgdoc(WW, WH, f'<g fill="{a.field}">{word}</g>'))
open(f"{a.out_prefix}-wordmark-white.svg", "w").write(svgdoc(WW, WH, f'<g fill="{a.structure}">{word}</g>'))

# ---- lockups ----
mark = open(a.mark).read()
mbody = re.search(r"<svg[^>]*>(.*)</svg>", mark, re.S).group(1)
MH = int(re.search(r'viewBox="0 0 \d+ (\d+)"', mark).group(1))

LK = 300
wscale = (LK * a.word_cap_frac) / CAP
gap, pad = LK * 0.15, LK * 0.12
LKW = LK + gap + WW * wscale + pad
mscale = LK / MH
wy = LK / 2 - (CAP / 2 + (ymax - CAP)) * wscale


def lockup(word_color):
    return svgdoc(LKW, LK,
                  f'<g transform="scale({mscale})">{mbody}</g>'
                  f'<g transform="translate({LK + gap},{wy:.1f}) scale({wscale})">'
                  f'<g fill="{word_color}">{word}</g></g>')


open(f"{a.out_prefix}-lockup.svg", "w").write(lockup(a.field))        # light backgrounds
open(f"{a.out_prefix}-lockup-dark.svg", "w").write(lockup(a.structure))  # dark backgrounds
print(f"wordmark {WW:.0f}x{WH:.0f} | lockup {LKW:.0f}x{LK} (light + dark)")
