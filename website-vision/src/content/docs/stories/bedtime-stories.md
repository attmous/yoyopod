---
title: "Lights Out: Bedtime Stories"
description: A parent starts tonight's story from the kitchen.
---

*Ben, 7, is in bed; his dad starts the story from the parent app downstairs.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## The moment

- 7:55 p.m.: Ben, 7, is tucked in, lights low, yoyopod on the nightstand
- His dad Tobias is downstairs finishing the dishes — story duty is his tonight
- Scene beat: from the parent app, Tobias picks up where last night's chapter ended and presses play (the parent app is future work — this is the target experience)
- Scene beat: upstairs, the story starts softly from the speaker; the glass stays dark and calm
- Scene beat: the chapter ends, playback stops on its own, and the room is quiet — no autoplay into chapter four

## What yoyopod does

- Remote playback: a parent starts, pauses, and stops audio on the device from the parent app
- Stories live on the device — local-first, so the bedtime ritual works even if the family Wi-Fi is down (how the remote command reaches the device offline is TBD)
- Resume-from-last-position across nights, so "where were we?" never happens (TBD)
- Bedtime-appropriate behavior: soft volume, dark glass, playback that ends rather than escalates (sleep-timer concept TBD)

## Behind the scenes

- How a play command travels from the parent app to the device — see [Parent app](/apps/parent-app/)
- How on-device story audio is organized and played — see [Listen](/apps/listen/)
- The handoff between remote control and Ben's own button (can he pause his own story? TBD)

## Why it matters

- The pillar made concrete: the parent app is not surveillance software — it is also the family remote control for good rituals
- For Ben: bedtime stories without a tablet glowing on his face
- For Tobias: presence at bedtime even on the nights he is stuck downstairs
- Screen-light by design: the richest media moment of Ben's day involves zero looking

## Open questions

- TODO: Does remote playback require the device to be online at that moment, and what is the offline fallback story?
- TODO: Who wins a control conflict — Ben's button press or the parent app command? (TBD)
- TODO: Is there a bedtime mode (volume cap, dimmed glass, no incoming calls) or is that scope creep for V1? (TBD)
- TODO: Where do the stories themselves come from — bundled content, parent-provided files, or partnerships? (TBD)
