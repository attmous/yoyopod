# Brand

Identity assets for yoyopod. Today this is the logo pack — the
wordmark, its colour set, and the rules for placing it.

This covers the brand mark only. For the on-device UI look, read
[`../design/README.md`](../design/README.md); for the physical shell
and its finishes, read
[`../hardware/enclosure/README.md`](../hardware/enclosure/README.md).

## The Mark

The mark *is* the wordmark: `yoyopod`, set in Figtree ExtraBlack (900),
lowercase, letter-spacing −2% em. There is no icon, no monogram, and no
glyph modification — the word on its own is the whole identity.

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

[`logo/png/`](logo/png/) — transparent background, 2048 px and 1024 px
wide (heights 678 px and 338 px). Same four colours, plus
`yoyopod-cream-on-navy-2048.png`, a ready-made reversed lockup on a
solid navy field.

Reach for the SVG when the medium takes vector and PNG everywhere
else.

**SVG caveat:** the SVGs are live text (`<text font-family="Figtree">`),
not outlined paths, and the font is *not* embedded. They render
correctly only where Figtree 900 is installed; anywhere else the
renderer silently substitutes another face and the mark is wrong. For
handoff to anyone outside the repo, send PNG, or outline the text
first. Converting these to outlined paths is worth doing and has not
been done.

## Rules

- Clear space: 0.3× wordmark height on all sides — already baked into
  every file, so do not crop into it
- Minimum size: 80 px on screen, 20 mm in print
- Never add outlines, shadows, or gradients
- Never recolour individual letters
- Never set it in title case or all caps
