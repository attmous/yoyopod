# YoyoPod Device UI — Implementation Handoff

For the agent (or human) implementing this design in `device/ui/`. The mockups
in this folder are **final** as of 2026-07-15. This document is the entry
point: what to build, in what order, what the runtime already gives you, and
what it's still missing. `README.md` holds the decision history; the HTML
files hold the normative pixel/behavior specs.

## The system in five rules

1. **Three gestures, one button.** press = advance/roll · double-press =
   open/activate · long-press ≥ 400 ms = go Home (pops the whole stack; no
   per-crumb back). The Whisplay prototype has **exactly one physical button**
   (`hardware/whisplay.rs`) — "PTT hold" is that same button remapped per
   screen via the passthrough policies (`OneButtonMachine::
   observe_ptt_passthrough`): on capture screens hold = talk, not Home. A
   dedicated PTT side button is a future-hardware option. Timing and state
   machine: `mockup_input_model.html` (single source of truth) — note the
   shipped timing config differs (item 14).
2. **Flat chrome.** No UI borders, no drop shadows. Fills + radius only
   (focused tile 16, hero art 18, plates 10, deck pill 12). Ink (`#1B1B1F`) is
   for text, glyphs, and the one surviving stroke — the **focus ring** (2 px
   ink outline + scale 1.1) on actionable controls (transport targets, call
   buttons). Characters (Blob, Owl, Cat, Bunny, Robot) are illustrations, not
   chrome: they keep 2 px ink outlines, never drop shadows.
3. **The wheel** is the only menu primitive: focused tile center-stage,
   scaled/dimmed peeks above and below, press rolls one step (180 ms, wraps,
   spoken label), double-press opens. Normative: `mockup_listen.html` §3.
4. **The arc hero** is the only player primitive: art/avatar with a progress
   ring, one play chip, bare side glyphs. Normative: `mockup_listen.html` §4
   (canonical `lv_arc`) with a bar fallback that needs zero new FFI.
5. **Voice carries the pre-readers.** Every focus change speaks the focused
   label; empty states and errors are spoken. Toggle: Setup → "Speak names".
   No flow may require reading to complete.

## File map (all in this folder)

| File | Normative for | UiScreen routes |
|---|---|---|
| `mockup_input_model.html` | gesture grammar, timing, Home/Ambient state machine | (cross-cutting) |
| `mockup_home.html` | Home stage, Blob, deck geometry + states | `Hub` |
| `mockup_listen.html` | **wheel + arc-hero primitives**, Listen flow, FFI additions table (§7), roles (§8) | `Listen`, `Playlists`, `RecentTracks`, `NowPlaying` |
| `mockup_listen_dark.html` | dark token swap (theme = tokens only) | same |
| `mockup_talk.html` | Talk flow, recording, Replay, call overlays | `Talk`, `TalkContact`, `IncomingCall`, `OutgoingCall`, `InCall` (+ new `Replay`; retires `Contacts`, `CallHistory`, `VoiceNote`) |
| `mockup_ask.html` | Ask flow (4 states + offline) | `Ask` |
| `mockup_setup.html` | Setup tree (wheel), Volume, Companion, Contacts, Theme, About | replaces `Power` |
| `mockup_system.html` | Loading + Error overlays | `Loading`, `Error` |
| `mockup_companions.html` (+`_dark`) | swappable Home characters | (asset variants) |

## Runtime work items (beyond RON asset edits)

Verified against the code; file references are the places to change.

| # | Item | Where | Size |
|---|---|---|---|
| 1 | `SelectionOffset` maps to `set_x_offset`; vertical wheel needs Y | `renderer/lvgl_renderer.rs:157` | XS |
| 2 | Wrap-aware `visible_range` for >6-item wheels (currently clamps) | `scene/deck.rs` | S |
| 3 | Native facade `set_scale` / `set_opacity` / offsets are no-ops — implement | `renderer/lvgl/facade.rs` | S |
| 4 | Long-hold emits `Back` (pop one); contract is pop-to-root | `input/machine.rs`, `application/input_router.rs` | XS |
| 5 | FFI additions: `lv_arc_*` + arc styles (+ `ElementKind::Arc`), `lv_obj_set_style_outline_color` (+pad), externs `lv_font_montserrat_14`/`_24`, `lv_obj_set_style_transform_scale` (or `lv_image_set_scale`) | `renderer/lvgl/ffi.rs`, `renderer/widgets/factory.rs` | M — full table: `mockup_listen.html` §7. **No shadow FFI** (flat pass removed the need) |
| 6 | theme.ron schema: `font_size` field (+ optional `arc_width`/`arc_rgb`) | `renderer/assets.rs`, `styling/` | S |
| 7 | New roles in `layouts.ron`/`theme.ron`/`scene/roles.rs` + required-role lists | per-file §roles tables | M |
| 8 | New A8 icons: playlist, recents, shuffle, mic, plus (56×56); play/pause/prev/next/close (24×24). Fix silent fallback-to-SETUP for unknown keys | `renderer/lvgl/icons.rs` | M |
| 9 | Voice-prompt-on-focus hook (TTS speaks focused label; interruptible; "Speak names" toggle) | app/intent layer | M |
| 10 | Route changes: Talk root = contacts; add `Replay`; retire `Contacts`/`CallHistory`/`VoiceNote`; `Setup` tree replaces `Power` | `router/routes.rs`, `device/protocol` | M |
| 11 | Move the voice-capture passthrough from `VoiceNote` to `TalkContact`, gated on the Record action being focused (today `TalkContact` = `NO_PASSTHROUGH`, so PTT on that screen is ignored) | `router/routes.rs` (`passthrough_policies`) | S |
| 12 | Ask stop path: barge-in-stop in the voice/speech worker (an `ask_start` while speaking halts playback) **or** a dedicated stop intent — today `start_work` rejects while busy, so "double-press to stop" does nothing | speech worker, `router/routes.rs` | M |
| 13 | Error overlay interactions: retry select target, a path that clears `snapshot.overlay.error` (else `runtime_preemption` re-pushes the overlay forever), 8 s Loading→Error + 4 s auto-retry timers | `router/routes.rs`, `application/navigator.rs` | M |
| 14 | Button timing: release before 400 ms = press / hold at least 400 ms = Home or PTT / 350 ms double window. Hardware testing retired the 180–400 ms dead zone because it discarded ordinary deliberate presses. | `input/config.rs`, `input/machine.rs`, `config/device/hardware.yaml` | S |

## Suggested build order

1. **Flat theme + deck pill** on existing screens (theme.ron token pass —
   immediate visible win, no new machinery).
2. **Wheel on Listen** (items 1–3, 7, 8): Listen root matches the shipped
   router already, so no route work — pure presentation.
3. **Arc hero** for NowPlaying — start with the bar fallback (zero FFI),
   upgrade to `lv_arc` when item 5 lands.
4. **Input remap** (item 4) + voice prompts (item 9).
5. **Talk v5** (route changes, item 10), then Ask, then Setup.
6. **System overlays** (Loading/Error) — smallest, do anytime.

Per-screen object budgets are in each spec (§budget); every screen fits the
60-object cap with ≥ 13 headroom.

## Acceptance checklist (per screen)

- Renders match the spec's device frames at 240×280 (RGB565 values from the
  token tables, not the CSS hexes).
- press / double-press / long-press behave per the screen's input-contract
  table; long-press lands on Home everywhere except capture screens, where
  hold = talk (PTT passthrough).
- Focus is visible without reading: fill + size (+ ring on controls).
- Focused label is spoken on every focus change (when Speak names is on).
- No UI borders or shadows anywhere; characters keep outlines.
- Object count within the spec's stated budget.

## Deliberately open (do not block on these)

Notifications on Home without auto-play · stuck-send retry policy · replay
cap (~20/contact suggested) · contact ordering (pinned suggested) ·
double-press window for small hands (350 ms default, test with kids) ·
parent gate on Setup · haptics · LCD washout escape hatch (darken stage tint
or 1 px self-color outline — token change, only if device testing shows the
need).
