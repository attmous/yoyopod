---
title: Canonical Structure
description: The config topology, its three rules (composition, secrets, board overlays), and the migration template.
---

Where configuration lives, who owns it, and the rules that keep it
composable. The goals: split authored config by ownership, compose it
into one typed runtime model, keep mutable user data out of tracked
config, and make secret boundaries explicit and validated.

## The config topology

| Path | Owns |
| --- | --- |
| `config/app/core.yaml` | app shell: `app`, `ui`, `logging`, `diagnostics` |
| `config/audio/music.yaml` | music policy, startup volume, media runtime paths |
| `config/device/hardware.yaml` | shared hardware truth: `input`, `display`, `communication_audio`, `media_audio`, `voice_audio` |
| `config/power/backend.yaml` | PiSugar transport, watchdog, polling, shutdown policy |
| `config/network/cellular.yaml` | cellular modem policy + transport |
| `config/voice/assistant.yaml` | voice policy + assistant defaults |
| `config/communication/calling.yaml` | non-secret SIP identity + calling policy |
| `config/communication/messaging.yaml` | messaging policy, message-store paths, voice notes |
| `config/communication/integrations/liblinphone_factory.conf` | repo-owned Liblinphone defaults |
| `config/people/directory.yaml` | paths for mutable people data + bootstrap seeds |
| `config/people/contacts.seed.yaml` | tracked bootstrap seed data only |

Untracked secrets: `config/communication/calling.secrets.yaml`. Mutable
runtime data lives under `data/` (`data/communication/`, `data/media/`,
`data/people/`) — never in tracked config.

## The three rules

1. **Composition** — the runtime consumes one composed, typed model, not
   ad-hoc YAML reads. (In the Rust runtime this is `RuntimeConfig::load`
   — see [Configuration Wiring](/runtime/configuration/).)
2. **Secret boundary** — tracked config must never contain SIP
   credentials; validation rejects `sip_password` or a tracked
   `secrets:` block. Credentials go in `calling.secrets.yaml` or env
   vars.
3. **Board overlays** — overrides mirror the same relative path under
   `config/boards/<board>/`; the only supported board is `rpi-zero-2w`.

## The migration template

When a new domain gets its own configuration, follow the established
seven steps: choose one public seam · split tracked config into
`config/<domain>/` · keep shared hardware truth in
`device/hardware.yaml` unless truly domain-owned · define the app-facing
seam · route mutable user data into `data/` · mirror the structure under
`config/boards/<board>/` · add focused build + Pi validation checks.

## Validation layout

The repo no longer carries separate unit-test trees: Rust workspace
checks live with `device/Cargo.toml` and `cli/Cargo.toml`; hardware
validation runs behind `yoyopod target deploy` and (Round 2)
`yoyopod target validate` — see the [Roadmap](/product/roadmap/).

:::caution[The historical half]
The canonical document's "Canonical Package Ownership" section and its
per-domain migration patterns describe the **retired Python layout**
(`yoyopod/integrations/…`, `.py` seams). The current per-domain homes are
the Rust `device/*` crates — see [Work Areas](/architecture/work-areas/)
and the runtime guide's [Source Map](/runtime/advanced/source-map/). The
config topology and rules above remain current.
:::

:::note[Canonical source]
Condensed from
[`docs/architecture/CANONICAL_STRUCTURE.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/CANONICAL_STRUCTURE.md).
:::
