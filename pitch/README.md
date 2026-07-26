# yoyopod pitch

The five-minute hackathon presentation lives here as a self-contained feature
area. The documentation site exposes it at `/pitch/` through the small route
shim in `docsite/website/src/pages/pitch/index.astro`.

## Preview

From `docsite/website/`:

```sh
npm run dev
```

Then open `http://localhost:4321/pitch/`.

## Build

From `docsite/website/`:

```sh
npm run build
```

## Structure

- `src/pages/Pitch.astro` — presentation markup and interaction
- `src/styles/pitch.css` — projector, mobile, and reduced-motion styles
- `src/assets/` — local presentation imagery, device UI, avatars, and brand glyph
- `scripts/render-pitch-talk.mjs` — regenerates the composed Talk device screen

From the repository root, the renderer uses the `sharp` dependency installed
by the documentation site:

```sh
node pitch/scripts/render-pitch-talk.mjs
```
