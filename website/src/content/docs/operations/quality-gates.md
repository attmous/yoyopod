---
title: Quality Gates
description: The verification policy — which checks count, how hardware validation works today, and what to report.
---

What counts as verification before a change merges — and just as
important, what to *say* about what you ran.

## Rust build checks

Focused, per changed crate:

```bash
cargo check --manifest-path device/Cargo.toml -p yoyopod-runtime --locked
cargo check --manifest-path device/Cargo.toml -p yoyopod-ui --locked
# …same pattern for -p yoyopod-media / -voip / -network / etc.
```

Broad workspace change:

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
```

CLI changes get all three:

```bash
cargo check  --manifest-path cli/Cargo.toml
cargo test   --manifest-path cli/Cargo.toml
cargo clippy --manifest-path cli/Cargo.toml --all-targets
```

:::caution[Native LVGL / Whisplay changes]
For hardware-facing features, local checks are not parity — validate
against the **CI-built ARM artifact for the exact commit** before
claiming hardware works. (The UI guide's rule: never rebuild LVGL on
the Pi.)
:::

## Hardware checks

The Pi is the real validation target for runtime, display, input,
audio, SIP, modem, and power:

```bash
git rev-parse HEAD                       # know your exact commit
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>
```

Until Round 2 restores `target validate`
([Roadmap](/product/roadmap/)): `target status`, `target logs --follow`,
`journalctl -u yoyopod-dev.service -f` — and exercise the changed
surface with human eyes.

## Reporting — say what actually ran

Every hardware validation report should state:

- the branch and **exact commit SHA**
- the artifact name + CI run ID it deployed
- the Pi command results
- whether the dev service was left running
- the manual validation steps performed, and their outcomes

The norm behind the checklist: report checks that ran, not checks that
should have run. If your change is outside the currently gated surface,
say so plainly — see
[Contributor Workflow](/operations/contributor-workflow/).

:::note[Canonical source]
Condensed from
[`docs/operations/QUALITY_GATES.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/QUALITY_GATES.md)
(titled "Verification Policy" in the document itself).
:::
