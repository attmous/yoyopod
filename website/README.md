# yoyopod docs website

The documentation site for yoyopod, built with
[Astro Starlight](https://starlight.astro.build). Local-only for now — no CI
or publishing pipeline yet.

## Commands

Run from this directory:

| Command | Action |
| --- | --- |
| `npm install` | install dependencies |
| `npm run dev` | dev server at `localhost:4321` |
| `npm run build` | production build to `./dist/` (also runs the Pagefind search index and link checks) |
| `npm run preview` | serve the production build (search only works here, not in dev) |
| `npm run sync:mockups` | re-copy the normative UI mockups from `device/ui/assets/ui/` into `public/mockups/` |

## Content layout

- `src/content/docs/ui/` — the **UI System Guide** flagship section:
  hardware → driver → LVGL → framework → input → playbook.
- `src/content/docs/runtime/` — the **Runtime & Workers Guide** flagship
  section: protocol → supervisor → the six domain workers.
- The other sections (`product/`, `architecture/`, `hardware/`,
  `features/`, `operations/`) are curated pages **condensed from the
  canonical Markdown** under `docs/` in the repo root. The repo docs stay
  the source of truth — each page carries a "Canonical source" note; keep
  content condensed, never wholesale-duplicated.
- `public/mockups/` — copied snapshots of the design mockups; canonical
  source is `device/ui/assets/ui/`. Refresh with `npm run sync:mockups`.
- `src/assets/diagrams/` — hand-authored theme-aware SVG diagrams, inlined
  as Astro SVG components.
- Sidebar and site config: `astro.config.mjs`. Theme palette (derived from
  the device UI's design tokens): `src/styles/custom.css`.
