# yoyopod vision docs

The public docs site for yoyopod, served at `https://docs.yoyopod.com`: what
the product is today and the experience it is being built toward — for
families, builders, and anyone curious about the why. Fully drafted across
families, user stories, applications, builders, and company sections.

This is deliberately a second site. The as-built engineering documentation
lives in [`docsite/website/`](../www/) and remains the source of truth for what
is actually implemented today; when the two disagree, the as-built site wins.
This site wears the startup's brand kit — "Sunrise & Midnight": marigold amber
on midnight indigo and warm paper, documented at `/company/brand-kit/`. The
as-built site keeps its coral device-token theme, so the two are visually
unmistakable.

## Commands

Run from this directory:

| Command | Action |
| --- | --- |
| `npm install` | install dependencies |
| `npm run dev` | dev server at `localhost:4322` (as-built site keeps 4321) |
| `npm run build` | production build to `./dist/` |
| `npm run preview` | serve the production build at `localhost:4322` |

## Content layout

- `src/content/docs/families/` — end-user guide: setup, everyday use, safety.
- `src/content/docs/stories/` — persona-driven user stories (kids 7–14 and
  their parents), grounded in the V1 pillars.
- `src/content/docs/apps/` — the applications: Listen, Talk, Locate, the
  parent app, Setup, and what comes next.
- `src/content/docs/builders/` — hardware platform, software platform, and
  the developer guide.
- `src/content/docs/company/` — mission, principles, anti-positioning,
  roadmap.
- Sidebar and site config: `astro.config.mjs`. Theme: `src/styles/custom.css`.

## Content status convention

Two states, mirrored by sidebar badges in `astro.config.mjs`:

- **As-built** (no badge) — condensed from as-built docs; ends with a
  `:::note[Sources]` aside.
- **Vision** (`Vision` badge) — `:::note[The vision]` aside; describes the
  target experience yoyopod is designed to deliver, with inline
  "*Design direction — not built yet.*" markers on hybrid pages. Not a
  description of today's prototype.

The H2 skeleton must survive every state transition.

## Deployment

Built and uploaded manually to the VPS alongside the `www/` landing page —
see [`docs/operations/WEB_DEPLOY.md`](../../docs/operations/WEB_DEPLOY.md).
