# yoyopod vision docs

The **target-state** documentation site for yoyopod: the structure a complete
hardware + software product would ship with — families, user stories,
applications, builders, company. Every page except the landing and section
indexes is a **structured stub** (headings + bullet outlines + open
questions): the information architecture is decided, the content is not
written yet.

This is deliberately a second site. The as-built engineering documentation
lives in [`website/`](../website/) and remains the source of truth for what
is actually implemented today. Teal accent = vision site; coral accent =
as-built site.

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
  parent app, Setup, and the future parking lot.
- `src/content/docs/builders/` — hardware platform, software platform, and
  the developer guide.
- `src/content/docs/company/` — mission, principles, anti-positioning,
  roadmap.
- Sidebar and site config: `astro.config.mjs`. Theme: `src/styles/custom.css`.

## Stub convention

Every stub page carries a `:::caution[Vision stub]` aside, 2–4
section-family H2s with bullet outlines, and an "Open questions" list of
TODOs. Filling a stub means replacing the outline with prose and deleting
the caution — the H2 skeleton should survive.
