# yoyopod vision docs

The **target-state** documentation site for yoyopod: the structure a complete
hardware + software product would ship with — families, user stories,
applications, builders, company. Every page except the landing and section
indexes is a **structured stub** (headings + bullet outlines + open
questions): the information architecture is decided, the content is not
written yet.

This is deliberately a second site. The as-built engineering documentation
lives in [`website/`](../website/) and remains the source of truth for what
is actually implemented today. This site wears the startup's brand kit —
"Sunrise & Midnight": marigold amber on midnight indigo and warm paper,
documented at `/company/brand-kit/`. The as-built site keeps its coral
device-token theme, so the two are visually unmistakable.

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

## Content status convention

The ideal structure is fixed; real content is condensed into it wherever
the repository has it. Three states, mirrored by sidebar badges in
`astro.config.mjs`:

- **Filled** (no badge) — condensed from as-built docs; ends with a
  `:::note[Sources]` aside.
- **Partial** (`Partial` badge) — real sections plus inline
  "*Placeholder — no as-built content yet.*" markers.
- **Placeholder** (`Placeholder` badge) — `:::caution[Placeholder]` aside;
  the outline is the target structure. The badge map is the gap list.

The H2 skeleton must survive every state transition.
