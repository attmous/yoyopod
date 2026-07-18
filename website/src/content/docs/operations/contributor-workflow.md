---
title: Contributor Workflow
description: From fresh checkout to a credible PR — the reading order, the fast loop, and the honesty norms.
---

The shortest path to a contribution that reviewers can trust.

## Read first, in this order

Repo `README.md` → `docs/README.md` →
[Development Guide](/operations/development-guide/) →
[System overview](/runtime/overview/) →
[Quality Gates](/operations/quality-gates/) → `rules/project.md` +
`rules/architecture.md`.

## The fast local loop

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
cargo test  --manifest-path cli/Cargo.toml
# targeted while iterating:
cargo check --manifest-path device/Cargo.toml -p yoyopod-ui --locked
```

## Pick your doc path

| Working on… | Follow |
| --- | --- |
| Runtime / orchestration | `device/runtime/` → the worker crate → [Runtime Guide](/runtime/) → `rules/architecture.md` |
| Pi / setup | [Setup Contract](/operations/setup-contract/) → [Development Guide](/operations/development-guide/) → [Pi Dev Workflow](/operations/pi-dev-workflow/) → `rules/deploy.md` |
| UI / design | the [UI System Guide](/ui/) → `rules/design-fidelity.md` → `rules/lvgl.md` |
| Docs / guidance | READMEs → this page → `rules/project.md` |

## Before opening a PR

Run the relevant Rust checks (workspace `cargo check --locked`; the CLI
trio if you touched `cli/`). For hardware work: `target deploy` +
`target status` + `target logs --follow`, with eyes on the change. **If
your change is outside the currently gated surface, say so plainly in
the PR.**

## What a good PR looks like here

One coherent problem slice · updates docs when the contract changes ·
states what is now *enforced* vs. still *debt* · avoids fake
completeness · leaves the repo more navigable than it found it.

## Contributor traps

- Treating the staged quality gate as whole-repo cleanliness.
- Treating the setup contract as fully solved (it isn't — Round 4+).
- Mixing unrelated cleanup into architecture PRs.
- Moving complexity into a new file and calling it architecture.
- Updating plan docs while leaving source-of-truth docs stale.

Current hotspots where extra care pays: `device/runtime/` (supervision),
`device/ui/` + LVGL scene code (visual fidelity on hardware),
`cli/yoyopod/` (active rebuild), duplicated domain models drifting
across `device/` crates, and docs wording that overstates rebuilt-CLI
guarantees.

## If you only remember one thing

Be honest about the repo's current state — real foundation progress,
still alpha. Land executable improvements without pretending the
remaining debt disappeared.

:::note[Canonical source]
Condensed from
[`docs/operations/CONTRIBUTOR_WORKFLOW.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/CONTRIBUTOR_WORKFLOW.md).
:::
