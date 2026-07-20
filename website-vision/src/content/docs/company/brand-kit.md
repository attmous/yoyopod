---
title: "Brand Kit: Sunrise & Midnight"
description: "The startup's palette — marigold amber, midnight indigo, warm paper — and the story it tells."
---

*The product and startup palette, decided and in use: this site wears it.*

## The story

The kit spans a kid's day, which is exactly what the device does:

- **Marigold amber** — the primary. Morning light: the walk to school, the
  first solo errand, independence. Warm and optimistic without tipping into
  toy branding (see [What yoyopod Is Not](/company/what-we-are-not/)).
- **Midnight indigo** — the base. Calm evenings: bedtime stories, the
  screen that stays quiet. The grown-up depth that reassures parents.
- **Warm paper** — the neutrals. Analog and book-like, because the product
  is screen-*light*: paper is what calm looks like.

One rule holds it together: **amber is for action, indigo is for calm,
paper is for everything else.**

## The palette

| Swatch | Name | Hex | Role |
| --- | --- | --- | --- |
| <span class="swatch" style="background:#f6b02c"></span> | Marigold | `#f6b02c` | Primary accent on dark; buttons, links, highlights |
| <span class="swatch" style="background:#9a6206"></span> | Deep marigold | `#9a6206` | Primary accent on light surfaces (contrast-safe) |
| <span class="swatch" style="background:#ffe4ad"></span> | Morning haze | `#ffe4ad` | Amber tint for hovers and soft fills |
| <span class="swatch" style="background:#171528"></span> | Midnight | `#171528` | Dark base / brand ink |
| <span class="swatch" style="background:#232136"></span> | Dusk | `#232136` | Raised dark surfaces |
| <span class="swatch" style="background:#26233d"></span> | Indigo ink | `#26233d` | Body text on light surfaces |
| <span class="swatch" style="background:#fdf8ee"></span> | Paper | `#fdf8ee` | Light base |
| <span class="swatch" style="background:#f1e8d7"></span> | Cream | `#f1e8d7` | Raised light surfaces, cards |

## Usage rules

- Amber earns its attention: one primary action per surface, never amber
  body text on paper (use Deep marigold for links on light).
- Indigo is never "black" — brand ink is `#26233d`/`#171528`, not `#000`.
- Paper backgrounds by default; pure white only inside content like photos.
- The device UI keeps its own flat-light tokens (warm creams + coral) until
  a deliberate re-skin decision — the kit governs brand, web, app, and
  packaging first. The as-built docs site (`website/` in the repository)
  stays on the device tokens on purpose.

## Where it is implemented

- This site's theme: `website-vision/src/styles/custom.css` — the CSS
  custom properties are the reference values.
- The brand art: `src/assets/art/device-art.svg` (the landing hero) and
  `src/assets/art/internals-art.svg` (the exploded V0 view), both fixed
  to the kit's hexes so they read identically in either theme.
- The promo: [yoyopod in 30 Seconds](/start/promo/) — five looping scenes
  animated in the kit's colors (`src/styles/promo.css`).

## Open questions

- TODO: logo and wordmark — does the yoyo/orbit motif render in Marigold on
  Midnight, and is there a single-color variant
- TODO: typography — pick the brand type pairing (this site currently uses
  the system font stack)
- TODO: accessibility pass — freeze the contrast-checked pairings table
  (amber-on-midnight and deep-marigold-on-paper are verified; tints are not)
- TODO: decide if/when the device UI itself migrates from its coral
  flat-light tokens to the kit
