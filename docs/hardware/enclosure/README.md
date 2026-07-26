# Enclosure Wireframes

Industrial-design wireframes for the YoYoPod handheld shell — flat
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
editable source, the PNG is a convenience render. Edit the SVG.
