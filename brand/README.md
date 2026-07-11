# Brand assets

The did-it mark: a checkmark inspected through a magnifying glass — a claim held up to the light and
verified against the evidence.

## Files

| File | Use |
|---|---|
| `did-it.svg` | Primary mark — full colour on the rounded teal tile (app-icon / avatar). |
| `did-it-mono.svg` | Single-ink teal silhouette, transparent — one-colour contexts on light backgrounds. |
| `did-it-white.svg` | Single-ink off-white silhouette, transparent — for dark backgrounds. |
| `did-it-wordmark.svg` / `-white.svg` | The word alone (Sora SemiBold, outlined). |
| `did-it-lockup.svg` / `-dark.svg` | Mark + wordmark, horizontal. `-dark` recolours the wordmark off-white for dark backgrounds (the colour mark is kept — it reads on both themes). |

All SVGs are true vector — the wordmark is glyph **outlines**, so no font is needed to render them. The
README header swaps `did-it-lockup.svg` ⇄ `-dark.svg` by `prefers-color-scheme` via `<picture>`.

## Palette

| | Hex | Role |
|---|---|---|
| Deep teal | `#10403B` | Field / primary ink |
| Warm off-white | `#F2EFE6` | Structure (magnifier ring + handle) |
| Verified green | `#33C481` | The checkmark accent |

Wordmark type: **Sora SemiBold** (weight 600), SIL Open Font License 1.1.

## Regenerating

The mark is traced from `did-it-source.png` (the approved raster) into a clean layered SVG; the
wordmark and lockups are typeset from the font as outlines.

```bash
# deps: vtracer, fonttools, pillow, scipy, numpy  (+ Node @resvg/resvg-js to rasterise for the eyeball check)
python3 -m venv .venv && . .venv/bin/activate
pip install vtracer fonttools pillow scipy numpy

# mark: colour + mono + white (three binary passes: tile / structure / check)
python3 trace_logo.py did-it-source.png did-it.svg \
    --field '#10403B' --structure '#F2EFE6' --accent '#33C481'

# fetch Sora and instance to weight 600:
curl -sL -o sora-var.ttf "https://raw.githubusercontent.com/google/fonts/main/ofl/sora/Sora%5Bwght%5D.ttf"
python3 -c "from fontTools import ttLib; from fontTools.varLib.instancer import instantiateVariableFont as I; f=ttLib.TTFont('sora-var.ttf'); I(f,{'wght':600},inplace=True); f.save('sora-600.ttf')"

# wordmark + light/dark lockups  (the wordmark reads "did-it?" — the question the tool answers)
python3 build_lockup.py --text 'did-it?' --font sora-600.ttf --mark did-it.svg \
    --field '#10403B' --structure '#F2EFE6' --out-prefix did-it
```

`trace_logo.py` traces per colour (binary passes are smoother than colour mode, and the outer
background drops out cleanly). The tile is emitted as a true rounded-rect primitive, so the flat field
carries no tracing seam. The accent layer is gated by chroma on top of nearest-colour, so the neutral
anti-aliased edge pixels don't paint green slivers.
