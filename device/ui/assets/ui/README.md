# YoyoPod Device UI — Mockups & Design Specs

Static HTML design specs for the 240 × 280 Whisplay panel UI. Nothing in this
folder is compiled into the device binary — these are the canonical design
reference for what the LVGL renderer in `device/ui/src/` should produce.

Open any file in a browser. Each page renders the panel at 1:1 CSS pixels
inside a device frame, followed by the full token / geometry / behavior tables
an implementer needs.

## File inventory

| File | Covers | Theme | Status |
|---|---|---|---|
| `mockup_home.html` | Home: idle + 4 focus states, companion Blob, deck | light | ✅ consolidated |
| `mockup_listen.html` | Listen **v2**: wheel navigation + arc-hero NowPlaying — owns the wheel & arc primitives | light | ✅ redesigned |
| `mockup_listen_dark.html` | Dark token swap of the **retired v1** card/tab layout | dark | ⚠ superseded — regeneration pending |
| `mockup_talk.html` | Talk **v5**: contact wheel, TalkContact wheel, recording, Replay, de-boxed call overlays | light | ✅ redesigned |
| `mockup_ask.html` | Ask: idle / listening / thinking / answering | light | ✅ (still v1 card pattern — wheel migration pending) |
| `mockup_setup.html` | Setup root + Volume / Companion / Theme / About | light | ✅ (still v1 card pattern — wheel migration pending) |
| `mockup_input_model.html` | The three-gesture input contract (single source of truth) | — | ✅ consolidated |
| `mockup_companions.html` | Swappable Home companions: Owl / Cat / Bunny / Robot | light | ✅ |
| `mockup_companions_dark.html` | Same, dark token swap | dark | ✅ tracks light file |

Dark variants are strict token swaps — geometry, spacing, type and behavior are
byte-identical to their light counterpart. **Always edit the light file first**,
then mirror the change.

## The one input contract (consolidation decision)

Earlier revisions of these specs forked into two input models: a
single-hardware-button model (Home, Listen) and a touchscreen model (Input
Model v1, Talk v4). **The fork is resolved: there is one three-gesture grammar,
and it is independent of the input hardware.**

| Gesture | Meaning |
|---|---|
| press | advance focus (wrap) |
| double-press | open / activate the focused element |
| long-press (≥ 400 ms) | go Home — pops the whole stack (on Home: defocus) |
| PTT hold (side button) | contextual voice capture (Ask, walkie-talkie) |

Bindings:

- **Today (Whisplay prototype):** the main hardware button carries press /
  double-press / long-press; the side push-to-talk button carries PTT hold.
  This matches the shipped runtime (`router/routes.rs`: `AdvanceFocus`,
  `PttPress`/`PttRelease` passthrough).
- **Future (if final hardware has touch):** the whole panel becomes one big
  button carrying the same grammar. **Positional input (tap-on-row,
  drag-off-row) is dropped from the contract** — at 240 × 280 on a 1.69″ panel
  a 28 px row is a ~3.5 mm target, hopeless for small fingers. The screen is
  never a precision surface.

Why this is the kid-right call: the entire device is operable with one motor
skill ("press the button"), the grammar is teachable in one sentence — *press
to look around, press-press to go in, hold to go home, hold the side button to
talk* — and nothing depends on reading or aiming.

There is deliberately **no per-crumb Back gesture**: going one level up = hold
(→ Home) + re-enter. One reliable escape hatch beats a second navigation
concept; voice prompts make re-navigation legible for pre-readers. (The
shipped `OneButtonMachine` still maps long-hold to a one-screen `Back` — see
the runtime mapping below.)

Timing (from the Input Model doc, applies to button and touch alike):
release < 180 ms = press candidate · two presses ≤ 350 ms apart = double-press
· held ≥ 400 ms = long-press (press-ring feedback at the 400 ms threshold).

## Home / ambient resolution

The Home spec (deck always visible, press cycles slots) and Input Model v1
(nav hidden until long-press) disagreed. Resolution:

- **Home always shows the deck.** Kids learn by seeing; navigation hidden
  behind a 400 ms long-press is not discoverable at age 4.
- The full-bleed "Blob only, no deck" composition survives as the **Ambient
  state**: entered after the idle timeout on Home, exited by any input. It is a
  presence/screensaver state, not a navigation state.

## Pre-reader principles

The primary user may not read yet. Every screen follows:

1. **Color + glyph first** — category identity is carried by color (lime /
   peri / butter / coral) and glyph, never by text alone.
2. **Voice prompt on focus** — on focus change the device speaks the focused
   item's label ("Mama", "Morning Songs"). Toggle lives in Setup → "Speak
   names". This is the pre-reader bridge for list navigation.
3. **Text is for grown-ups** — labels stay on screen for parents and early
   readers, but no flow requires reading to complete.

## Mockup ↔ runtime mapping

The runtime (`device/ui/src/router/routes.rs`) predates these specs. Known
divergences an implementer must reconcile:

| Spec | Runtime today | Divergence |
|---|---|---|
| Home deck: Listen · Talk · Ask · Setup | `Hub` → Listen / Talk / Ask / **Power** | "Setup" replaces/extends `Power`. |
| Listen root: Playlists · Recents · Shuffle all | Listen → Playlists / RecentTracks / ShuffleAll | ✅ **resolved in v2** — the wheel root matches the shipped router (v1's Artists/Radio rows dropped). |
| Wheel menus (Listen v2 / Talk v5) | `DeckKind::List` + `SelectionOffset` exist | restyle, not new architecture — but `lvgl_renderer.rs:157` maps `SelectionOffset` to `set_x_offset` (vertical wheel needs a Y remap), `Deck::visible_range` clamps instead of wrapping (>6-item wheels need wrap-aware windowing), and the native facade's scale/opacity/offset setters are currently no-ops. |
| Arc-hero progress ring | progress emulated as child-obj fill width | `lv_arc` needs new FFI + `ElementKind::Arc`; specs include a bar-based fallback that ships with today's FFI. |
| Hard offset shadows, focus outline color, Montserrat 14/24 | not in FFI / theme schema | add `shadow_offset_x/y`, `outline_color`, font externs — or use the documented composed fallbacks. FFI table: `mockup_listen.html` §7. |
| Talk v4: contacts list **is** the Talk root | Talk → Contacts / CallHistory / VoiceNote | v4 deletes the intermediate branch; `CallHistory` route orphaned. |
| Talk v4: hold-to-record inside TalkContact | dedicated `VoiceNote` screen with PTT passthrough | v4 folds recording into TalkContact; `VoiceNote` route to retire or repurpose. |
| Replay queue (per contact) | `voice.play_latest` intent on TalkContact | Replay-as-screen is new. |
| Call overlays Incoming / Outgoing / InCall | same, `NavigationPolicy::Call` | ✅ aligned. |
| long-press = go Home (pop whole stack) | `OneButtonMachine` long-hold → `Back` → pop one screen | remap long-hold to pop-to-root (`input/machine.rs`, `application/input_router.rs`); per-crumb Back is gone from the contract. |
| voice prompt on focus advance | — | new: speak the focused label via the speaker; toggle in Setup. |
| — | `Loading` / `Error` overlays | not yet designed (open). |

## Open questions (consolidated)

Carried from the per-file "open questions" sections, still undecided:

1. **Notifications on Home** — how a new voice note surfaces without auto-play
   (badge on Talk slot / toast / deck pulse).
2. **Stuck-send retry policy** — suggested: silent retry once on reconnect,
   then surface on the contact avatar.
3. **Replay scoping** — cap per contact (suggested ~20, drop oldest).
4. **Contact ordering** — pinned (Setup-defined) vs recency. Leaning pinned:
   a 5-year-old's list shouldn't reshuffle.
5. **Press-ring color inside a slot** — always periwinkle vs focused slot's
   color.
6. **Haptics** — 10 ms buzz at the 400 ms long-press threshold, if final
   hardware has a motor.
7. **Loading / Error overlay design** — routes exist in the runtime, no mockup.
8. **Kid timing tolerances** — 350 ms double-press window needs testing with
   4–6-year-olds; may need to widen.

## Redesign changelog (2026-07-15, second pass — wheel + arc hero)

- **Listen v2 / Talk v5**: card + tab-strip + row lists retired in favor of the
  **wheel** — one large focused tile center-stage (the only boxed element),
  neighbors peeking scaled/dimmed above and below; press rolls one step
  (wraps), double-press opens. Breadcrumb tabs replaced by a single small
  context label. NowPlaying/Replay became the **arc hero**: cover art / avatar
  with the progress ring around it (`lv_arc`, bar fallback included).
- Call overlays de-boxed: full-bleed tinted stage, big avatar, round
  answer/hang-up chips — no cards, no pills.
- Every component in both files now carries an explicit **LVGL mapping**
  (canonical stock widget vs composed-from-today's-FFI) plus the minimal FFI
  additions table (`mockup_listen.html` §7 is normative).
- `mockup_listen_dark.html` is superseded (still shows v1) — banner added,
  regeneration pending. Ask/Setup still use the v1 card pattern — wheel
  migration pending user approval of the new look.

## Consolidation changelog (2026-07-15)

- Declared the three-gesture grammar canonical; rebound Input Model doc from
  "touch panel, no buttons" to hardware-agnostic (button today, touch later);
  dropped positional taps.
- Resolved Home vs Input Model: deck persistent on Home; blob-only frame
  reclassified as Ambient state.
- Talk v4 walkie-talkie: recording binds to the PTT side button on current
  hardware (matches runtime); drag-off-cancel is touch-only, button cancel =
  press main button while holding.
- Added Ask and Setup flow mockups (previously missing: 2 of the 4 deck
  categories had no spec).
- Added pre-reader principles (voice prompt on focus, color/glyph-first).
- Added this README as the folder's index + decision log.
