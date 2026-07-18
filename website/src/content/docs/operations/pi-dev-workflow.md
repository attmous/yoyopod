---
title: Pi Dev Workflow
description: The everyday dev-machine-to-board loop — commit, push, deploy, verify — with its inspection and troubleshooting commands.
---

The default contract, five steps: finish the change locally → commit →
push (CI must build `rust-device-arm64` for that exact commit) → deploy
that commit to the Pi → verify with your own eyes.

:::caution[No dirty-tree deploys]
`target deploy` installs the CI artifact for the **exact pushed
commit** — an uncommitted tree has no artifact and cannot deploy. This
is a feature: the binaries on the board always correspond to a commit.
:::

## One-time setup

```bash
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod
yoyopod target config edit        # host/user → pi-deploy.local.yaml
gh auth status                    # must pass
```

Keep `host`/`user` out of the tracked `deploy/pi-deploy.yaml`; the
stable board checkout is `project_dir: /opt/yoyopod-dev/checkout` — one
checkout, always (native LVGL rebuilds are expensive; ad-hoc per-branch
checkouts on the board are unsupported). Env fallbacks exist:
`YOYOPOD_PI_HOST`, `YOYOPOD_PI_USER`, `YOYOPOD_PI_PROJECT_DIR`.

## The daily loop

```bash
yoyopod target mode status
yoyopod target mode activate dev          # if needed
git add -p && git commit -m '…'
git push
yoyopod target deploy --branch <branch>   # or --sha <commit>
yoyopod target status
yoyopod target logs --follow
```

Two flags to know: `--wait-for-ci` when CI is still running (30-minute
timeout), and `--clean-native` after native LVGL/CMake input changes
(wipes the board's build dir).

## Inspection

| Command | Shows |
| --- | --- |
| `target status` | deployed SHA, processes, log tail |
| `target logs --lines 200` / `--errors` / `--filter comm` / `--follow` | remote logs, filtered |
| `target screenshot` (`--readback` for LVGL readback) | the glass, into `logs/screenshots/` |
| `target restart` | restart + startup verification |

Until Round 2 lands `target validate`
([Roadmap](/product/roadmap/)), validate manually:
`yoyopod target logs --follow` plus
`ssh <user>@<host> 'journalctl -u yoyopod-dev.service -f'`.

## When deploy fails

```bash
yoyopod target logs --lines 200 --errors
ssh <user>@<host> 'systemctl status yoyopod-dev.service --no-pager -l'
```

| Symptom | Cause → fix |
| --- | --- |
| artifact fetch fails | `gh` not authenticated → `gh auth login` |
| "CI in progress" | rerun with `--wait-for-ci` |
| CI failed | fix the commit — never deploy a broken build |
| service won't start | prod lane active → `target mode activate dev` |
| sync errors | checkout ownership wrong → check `/opt/yoyopod-dev/checkout` |

Also: retry transient `github.com` blips before treating them as real
failures.

:::note[Canonical source]
Condensed from
[`docs/operations/PI_DEV_WORKFLOW.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/PI_DEV_WORKFLOW.md).
:::
