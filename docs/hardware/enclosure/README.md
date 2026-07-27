# Enclosure Wireframes

Industrial-design wireframes for the yoyopod handheld shell — flat
orthographic views (top, front, right, back, bottom) plus a depth
section. These are design directions, not a released mechanical
contract: no CAD, no tooling drawings, no tolerance sign-off.

For the electronics these shells have to contain, read
[`../POWER_MODULE.md`](../POWER_MODULE.md) and
[`../AUDIO_STACK.md`](../AUDIO_STACK.md). For the on-screen UI that
lives behind the window, read [`../../design/README.md`](../../design/README.md).

## Directions

Two directions exist. They share the same 72 × 78 mm footprint,
front-face layout, and control scheme — they differ in depth and in
how the internals stack.

### v1 — 13 mm thin

[`v1/`](v1/) — the thin direction. 72 × 78 × 13 mm, fully annotated
with callouts 1–11 covering the display window, speaker rail, mic
port, PTT trim, scroll wheel, USB-C, screw bosses, name-tag recess,
wordmark deboss, and regulatory pad-print zone.

- [`v1/yoyopod-ortho-annotated.svg`](v1/yoyopod-ortho-annotated.svg)
  (+ `.png`) — five views with numbered callouts, the production notes
  block, and the internals note
- [`v1/yoyopod-ortho-clean.svg`](v1/yoyopod-ortho-clean.svg)
  (+ `.png`) — same geometry, no annotation, for reuse in decks and
  product pages

Open question carried on the drawing itself: 13 mm outside minus two
2.0 mm walls leaves 9 mm of internal stack for Pi Zero 2W + PiSugar 3
+ a 1200 mAh flat cell. That has to be verified before tooling — v2
exists because it probably does not close.

### v2 — 22 mm, stack that closes

[`v2/`](v2/) — the thicker direction, drawn against a real depth
ledger rather than a target. 72 × 78 × 22 mm, 2.5 mm uniform wall,
Pi Zero 2W and PiSugar 3 side by side on one layer instead of
stacked, and a larger 2500 mAh cell.

- [`v2/yoyopod-v2-ortho-annotated.svg`](v2/yoyopod-v2-ortho-annotated.svg)
  — five views with dimensions and view labels
- [`v2/yoyopod-v2-ortho-board.png`](v2/yoyopod-v2-ortho-board.png) —
  rendered board of the annotated ortho
- [`v2/yoyopod-v2-ortho-clean.svg`](v2/yoyopod-v2-ortho-clean.svg) —
  unannotated geometry
- [`v2/yoyopod-v2-section.svg`](v2/yoyopod-v2-section.svg) (+ `.png`)
  — depth section looking down through the device, front face up,
  with the layer-by-layer ledger
- [`v2/colorways/`](v2/colorways/) — the four finishes
- [`v2/model/`](v2/model/) — the 3D model

The v2 depth ledger, as drawn:

| Layer | Depth |
| --- | --- |
| front wall | 2.5 mm |
| display module | 2.5 mm |
| gap | 0.5 mm |
| Pi Zero 2W + PiSugar 3 (same layer) | 7.0 mm |
| gap | 1.0 mm |
| battery — 2500 mAh flat cell | 6.0 mm |
| back wall | 2.5 mm |
| **total** | **22.0 mm** |

## Finishes

Four colourways, all on v2 geometry. The shell and accent hexes below
are decoded from the model materials and match the ortho drawings
exactly.

| Finish | Shell | Accent / light-pipe |
| --- | --- | --- |
| Cloud·Sky | `#e9edf2` | `#05cae9` |
| Mint·Forest | `#c9e6d4` | `#1f7d5d` |
| Bubblegum | `#f9c9da` | `#e8437f` |
| Tangerine | `#ffd2a8` | `#f26b1d` |

Shared across all four: glass `#13161f`, dark trim `#3a3742`, rubber
`#2b2a32`.

[`v2/colorways/`](v2/colorways/) holds, per finish, a recoloured
unannotated ortho (`yoyopod-ortho-<finish>.svg` + `.png`, same 850×655
geometry as the v2 clean ortho) and a small three-quarter product
render (`render-<finish>.png`).

## 3D Model

[`v2/model/`](v2/model/) is the v2 shell as geometry — 33 904
vertices, 12 440 faces, 78 material groups, split into `shell`,
`glass`, `dark`, `lightpipe`, `accent`, and `rubber`.

- `yoyopod-v2-<finish>.glb` — self-contained, materials embedded, one
  per finish. GitHub previews these in the browser; start here.
- `yoyopod-v2.obj` — shared geometry, identical for all four finishes,
  so it is stored once
- `yoyopod-v2-<finish>.mtl` — the per-finish material set

The OBJ carries `mtllib yoyopod-v2.mtl`, so `yoyopod-v2.mtl` is
present as the default and is a copy of the Cloud·Sky set — the OBJ
loads with a finish applied out of the box. To load a different
finish, either copy that finish's `.mtl` over `yoyopod-v2.mtl` or edit
the `mtllib` line on line 1. Nothing else in the OBJ changes between
finishes.

The model is a design study exported from a browser-based stage, not
parametric CAD: it is watertight enough to look at and to render, but
it is not a manufacturing model and has no feature history.

## Shared Notes

Both directions assume:

- R8.5 mm corner radius, R6 mm edge blends, 1.0° draft on vertical
  walls
- PC/ABS shell, parting line on the side-wall centre and hidden at the
  button trims
- 2.4″ 240 × 280 non-touch display, window flush to ±0.05 mm,
  hard-coated glass
- PTT over a TPU light-pipe ring and a detented push-click scroll
  wheel on the right wall
- USB-C on the bottom, carrying charge and audio
- back face: 4 × T6 screws, name-tag recess, wordmark deboss, and a
  regulatory pad-print zone

v2 additionally calls for coring out the screw bosses and molding the
speaker box (≥ 5 cm³) into the rail-side wall.

## Source Format

Every drawing is hand-authored SVG at a fixed viewBox — the SVG is the
editable source, the PNG is a convenience render. Edit the SVG. The
`render-*.png` files under `v2/colorways/` are the exception: they
come out of the 3D stage, so re-render them from the model rather than
editing them.

## See Also

[`../../product/ONE_PAGER.pdf`](../../product/ONE_PAGER.pdf) is the
customer-facing one-pager built on these v2 renders — same device,
positioning copy instead of dimensions.
