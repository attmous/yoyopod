---
title: "Lights Out: Bedtime Stories"
description: A parent starts tonight's story from the kitchen.
---

*Ben, 7, is in bed; his dad starts the story from the parent app downstairs.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## The moment

It is 7:55 p.m. Ben, 7, is tucked in, lights low, yoyopod on the nightstand. Story duty is his dad's tonight — and his dad, Tobias, is downstairs with his hands in the dishwater.

Tobias dries one hand, opens the yoyopod app, and taps Ben's yoyopod. The app remembers where last night ended — halfway into chapter three — and offers to pick up from there. He taps play.

A moment later, upstairs, the story begins. Softly: bedtime volume, not living-room volume. The canvas stays dark — nothing glows, nothing scrolls, there is nothing to watch. Ben lies in the dark while the story plays and his own imagination does the pictures.

Twenty minutes later the chapter ends, and playback simply stops. No sliding into chapter four, no "up next," no cliff to negotiate. The room goes quiet — and by then, so has Ben.

## What yoyopod does

A parent can start, pause, and stop the device's audio from the yoyopod app. The tap in the kitchen travels from the app to yoyocloud, and from yoyocloud down to the device — the phone and the yoyopod never talk to each other directly, which is why this works exactly the same whether Tobias is downstairs or away for the night.

The story itself never travels at all. It is already on the device, put there earlier through the app's content loading — so what crosses the network is only the instruction, a few bytes of "play chapter three." The audio plays from the device's own storage, which is why bedtime never buffers.

The ritual is shaped for the hour it lives in. The app resumes from where the last session ended, so "where were we?" never happens. Playback ends rather than escalates: a chapter finishes and stops. Volume stays soft, the canvas stays dark, and nothing about the experience asks Ben to open his eyes.

And Ben's own button still works the way it always does — see [using the button](/families/using-the-button/). If the family Wi-Fi is down, the tap in the kitchen can't reach upstairs; but the stories are on the device, so the ritual survives on its own: Ben's button, or a dad on the stairs, starts chapter three just as well. The network makes bedtime more convenient — it was never what made it possible.

## Behind the scenes

The path is deliberately indirect: the yoyopod app talks only to yoyocloud, and yoyocloud passes the play command down its standing link to the device. On the device, the Media Engine — the same engine behind [Listen](/apps/listen/) — receives the command, plays the chapter from local storage, and reports back honestly as playback starts, pauses, and completes, so the app in the kitchen shows what the nightstand is actually doing rather than what it hopes is happening.

The device half of this flow — accepting playback commands from yoyocloud and playing strictly local files — is specified on the [Media Engine](/builders/software/media-engine/) page. The app half belongs to the [App Platform](/builders/software/apps/) and the [Parent App](/apps/parent-app/) — and the app's deliberately narrow V1 scope is exactly where this story's biggest decision lives, below.

## Why it matters

The yoyopod app is not surveillance software, and this scene is the proof: the same app that shows a live-ish dot on a map is also the family's remote control for good rituals. It starts bedtime stories.

For Ben, the richest media moment of his day involves zero looking — no tablet propped on the blanket, no glowing rectangle at exactly the hour glowing rectangles do the most harm. The stories on the device were chosen by his parents, live on the device, and end when they end.

For Tobias, it is presence at bedtime even on the nights he is stuck downstairs. He picked the story, he pressed play, and tomorrow at breakfast he will be asked what happens next — which is the kind of app notification worth having.

## Open questions

- **Scope.** Remote story-start is, strictly, a sixth job for an app scoped to five — pairing, whitelist, location, content loading, the Help Agent builder. Adopt it into V1 because it rides on machinery the device side already defines, or hold it for V2 and let first-year families start stories with the button?
- **Who wins.** Adopt "the button in the room wins" — Ben's press pauses or stops the story regardless of what the app ordered — or give the app the last word? A bedtime remote that overrides the child in the room is a very different product from one that defers.
- **Bedtime mode.** Adopt a real bedtime mode — volume cap, dimmed canvas, incoming calls held until morning — or keep V1 to soft defaults and no special mode, and accept that as honest scope control?
- **Where the stories come from.** Bundled starter stories, family-loaded audio only, or content partnerships — the content loading job needs this answered before the ritual works out of the box on night one.
