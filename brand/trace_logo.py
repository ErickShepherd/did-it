#!/usr/bin/env python3
"""Trace a flat, hard-edged logo raster into a clean layered SVG — one binary vtracer pass per
colour region (binary tracing is smoother than vtracer's colour mode), with the outer background
dropped and, optionally, a perfect rounded-rect tile instead of a traced one.

Model: a flat mark has up to three roles — a dark FIELD (tile/background ink), a light STRUCTURE
(the main shape), and an optional saturated ACCENT (a highlight). The accent is found by nearest-colour
to the accent anchor AND a chroma (saturation) gate: nearest-colour alone misassigns the near-neutral
grey pixels on every field/structure edge (they can fall nearest the accent of any hue) and paints
slivers; the chroma gate drops them. Works for warm or cool accents alike.

Outputs (from OUT=foo.svg): foo.svg (full colour), foo-mono.svg (field-ink silhouette, transparent),
foo-white.svg (structure-ink silhouette, transparent). --no-tile omits the tile from foo.svg.

Deps: vtracer, pillow, scipy, numpy.  Usage:
  trace_logo.py SRC.png OUT.svg --field '#2E3A4E' --structure '#F4F1E8' [--accent '#E0A94A']
                [--chroma 40] [--luma 140] [--no-tile] [--tile-radius-frac 0.12]
"""
import argparse, os, re, tempfile
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, label
import vtracer

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--field", required=True); ap.add_argument("--structure", required=True)
ap.add_argument("--accent", default=None)
ap.add_argument("--chroma", type=int, default=40, help="min channel spread to count as accent")
ap.add_argument("--luma", type=int, default=140, help="brightness split: >= is structure, < is field")
ap.add_argument("--no-tile", action="store_true", help="omit the rounded tile (transparent mark)")
ap.add_argument("--tile-radius-frac", type=float, default=0.12)
a = ap.parse_args()

def hexrgb(s):
    s = s.lstrip("#")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], float)


rgb = np.asarray(Image.open(a.src).convert("RGB"), float)
h, w = rgb.shape[:2]
luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
chroma = rgb.max(-1) - rgb.min(-1)

# accent = nearest to the accent anchor AND saturated. The chroma gate is what makes it robust: the
# neutral grey AA pixels on every field/structure edge can fall NEAREST the accent anchor (any hue),
# so nearest-colour alone paints slivers; requiring chroma > threshold drops them. Works for any
# accent hue (warm or cool), unlike a directional R-B test.
anchors = [hexrgb(a.field), hexrgb(a.structure)] + ([hexrgb(a.accent)] if a.accent else [])
nearest = np.argmin(np.stack([((rgb - anc) ** 2).sum(-1) for anc in anchors], -1), -1)
accent = ((nearest == 2) & (chroma > a.chroma)) if a.accent else np.zeros((h, w), bool)
offish = (~accent) & (luma >= a.luma)          # structure OR outer background (both bright)
lab, _ = label(offish)
border = (set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])) - {0}
outer = np.isin(lab, list(border))             # border-connected bright region = surrounding background
tile = ~outer
structure = binary_dilation(offish & ~outer, iterations=1)   # +1px overlaps field edge, kills seam
accent = binary_dilation(accent, iterations=1) if a.accent else accent

PARAMS = dict(colormode="binary", mode="spline", filter_speckle=6,
              corner_threshold=20, length_threshold=4.0, splice_threshold=45, path_precision=8)


def trace(mask, tag):
    img = np.where(mask, 0, 255).astype(np.uint8)
    with tempfile.TemporaryDirectory() as t:
        p, s = os.path.join(t, f"{tag}.png"), os.path.join(t, f"{tag}.svg")
        Image.fromarray(img, "L").convert("RGB").save(p)
        vtracer.convert_image_to_svg_py(p, s, **PARAMS)
        return re.findall(r"<path[^>]*/>", open(s).read())


def recolor(paths, color):
    return "".join(re.sub(r'fill="#[0-9A-Fa-f]{6}"', f'fill="{color}"', p) for p in paths)


struct_paths = trace(structure, "struct")
accent_paths = trace(accent, "accent") if a.accent else []

# tile: a true rounded-rect primitive sized to the mark, so the flat field carries no trace seam
tile_svg = ""
if not a.no_tile:
    ys, xs = np.where(tile)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    full = np.where(tile.sum(1) >= 0.98 * (x1 - x0))[0]
    r = int(full.min() - y0) if len(full) else int(a.tile_radius_frac * (x1 - x0))
    tile_svg = (f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" '
                f'rx="{r}" ry="{r}" fill="{a.field}"/>')


def svg(*groups):
    body = "".join(groups)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}">{body}</svg>\n')


layers = tile_svg + f'<g>{recolor(struct_paths, a.structure)}</g>'
if a.accent:
    layers += f'<g>{recolor(accent_paths, a.accent)}</g>'
open(a.out, "w").write(svg(layers))

# single-ink silhouettes (structure + accent flattened), transparent, no tile
sil = struct_paths + accent_paths
base = os.path.splitext(a.out)[0]
open(f"{base}-mono.svg", "w").write(svg(f'<g>{recolor(sil, a.field)}</g>'))
open(f"{base}-white.svg", "w").write(svg(f'<g>{recolor(sil, a.structure)}</g>'))
print(f"wrote {a.out} (+ -mono, -white); struct/accent paths = "
      f"{len(struct_paths)}/{len(accent_paths)}; tile={'no' if a.no_tile else 'rect'}")
