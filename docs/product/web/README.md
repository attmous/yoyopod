# Web Pack

Two self-contained marketing pages for yoyopod, exported as a locked
pair. They are design artefacts in the same family as
[`../ONE_PAGER.pdf`](../ONE_PAGER.pdf) and
[`../PRODUCT_VIDEO.mp4`](../PRODUCT_VIDEO.mp4) — built on the V2
enclosure study, not on shipped hardware.

This is *not* the developer documentation site. That is the Astro
project under [`../../../docsite/website/`](../../../docsite/website/README.md),
which is generated from the markdown in [`../../`](../../README.md).

- [`index.html`](index.html) — coming-soon landing page. Navy field,
  animated teaser art, "Something small is coming.", a launch label
  reading Spring 2027, and an email-capture block
- [`docs.html`](docs.html) — a single-page customer-facing device
  guide, self-described as "v2 hardware · draft — July 2026". Sections:
  Start here, Hardware (body, controls, display, audio, power,
  finishes), System (architecture, connectivity, security), For
  parents (setup, daily use, care), For developers, Open items

The two link to each other, so they only work as a pair — keep them in
the same folder wherever they are hosted.

## Before Hosting These

**The email capture does not capture anything.** The input is
component state and the button only flips its own label to "You're on
the list ✓". There is no form action, no endpoint, no network call.
Anyone who types an address gets a success affordance and is not on any
list. Wire it to something real before this page goes anywhere public.

**They are dated.** "Spring 2027", a 2026 copyright, and a July 2026
draft stamp are baked into the exported bundles.

**They need JavaScript.** Each file boots a bundler shim that mints
blob URLs for its inlined resources and runs an in-browser transform
before painting. With JS disabled you get a "This page requires
JavaScript" notice and nothing else. The two `fetch()` calls in each
file read those local blobs — no external requests, no third-party
hosts, and the Figtree woff2 faces are inlined, so the pages do work
fully offline.

## Regenerating

These are build outputs. The source that produced them is not in this
repo, so they cannot be rebuilt here — editing means editing 200 KB of
generated bundle by hand, which is not worth doing. Re-export from the
original tool and replace both files together.

## Where They Disagree With The Repo

Neither page is an implementation contract. Read
[`../../README.md`](../../README.md) for the source-of-truth order —
current code first, these artefacts well below it. Known conflicts as
of this export:

| Claim on the page | What the repo says |
| --- | --- |
| `docs.html`: "kids aged 5–10" | ages 7–14 in [`../PRODUCT_DEFINITION.md`](../PRODUCT_DEFINITION.md) and [`../LANDING_PAGE_POSITIONING.md`](../LANDING_PAGE_POSITIONING.md); 7–13 in the repo [`README.md`](../../../README.md) |
| `docs.html`: "the single source of truth for the v2 hardware" | V2 is a design study — see [`../../hardware/enclosure/README.md`](../../hardware/enclosure/README.md). No CAD, no tooling, no tolerance sign-off |
| `docs.html`: "PTT + rocker" | "glowing PTT + click-wheel" elsewhere in [`../README.md`](../README.md) |

The age range is worth settling — three different answers now ship
across the repo and these pages.
