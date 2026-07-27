# Brand

Identity assets for yoyopod. Today this is the logo pack — the
wordmark, its colour set, and the rules for placing it.

This covers the brand mark only. For the on-device UI look, read
[`../design/README.md`](../design/README.md); for the physical shell
and its finishes, read
[`../hardware/enclosure/README.md`](../hardware/enclosure/README.md).

## The Mark

The mark *is* the wordmark: `yoyopod`, set in Figtree ExtraBlack (900),
lowercase, natural spacing — with one deliberate modification. The `p`
sits 1/14 em below the baseline. That is the yo-yo caught mid-bounce,
and it is the whole idea; there is no icon, no monogram, and no other
glyph change.

The drop is always exactly 1/14 em — 4 px at a 56 px setting, 14.3 px
at 200 px. More reads as a typesetting error, less is invisible. It is
already baked into every file here, so use the files rather than
re-deriving it.

Lowercase is not optional. `Yoyopod` and `YoyoPod` are wrong
everywhere, including prose.

Font: [Figtree](https://fonts.google.com/specimen/Figtree) 900, OFL
licensed.

## Colours

| Name | Hex | Use |
| --- | --- | --- |
| navy | `#2b2836` | primary, on light backgrounds |
| cream | `#f0eee9` | on navy or other dark backgrounds |
| white | `#ffffff` | on photos and saturated colour |
| black | `#000000` | single-colour print |

The device accent colours (Cloud·Sky `#05cae9`, and the rest of the
four finishes in
[`../hardware/enclosure/README.md`](../hardware/enclosure/README.md))
are enclosure colours, not logo colours. Do not set the wordmark in
them.

## Files

[`logo/svg/`](logo/svg/) — vector, one file per colour:
`yoyopod-navy.svg`, `-cream`, `-white`, `-black`.

[`logo/png/`](logo/png/) — transparent background, widths 2048, 1024,
512, and 256 px. Same four colours, plus
`yoyopod-cream-on-navy-2048.png`, a ready-made reversed lockup on a
solid navy field.

Reach for the SVG when the medium takes vector and PNG everywhere
else.

**SVG caveat:** the SVGs are live text — one `<text
font-family="Figtree">` element per glyph, at hardcoded x positions —
not outlined paths, and the font is *not* embedded despite what the
upstream export note claims. They render correctly only where Figtree
900 is installed. Anywhere else the renderer substitutes another face
and, because the per-glyph positions were computed against Figtree's
metrics, the letters land at the wrong spacing as well as in the wrong
typeface. For handoff to anyone outside the repo, send PNG, or outline
the text first. Converting these to outlined paths is worth doing and
has not been done.

## Rules

- The `p` drop is always 1/14 em — never deeper, never shallower
- Clear space: 0.3 em on all sides — already baked into every file, so
  do not crop into it
- Minimum size: 80 px on screen, 20 mm in print. Below that the drop
  stops reading; set the name in plain type instead of shrinking the
  mark further
- Never add outlines, shadows, or gradients
- Never recolour individual letters
- Never set it in title case or all caps
