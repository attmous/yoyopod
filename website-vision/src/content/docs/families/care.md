---
title: Charging & Care
description: Battery life, charging, cleaning, and keeping it healthy.
---

*Keep the device charged, clean, updated, and out of the washing machine.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## What you'll need

*Proposed — the ideal design, not yet adopted.*

Very little, and all of it ordinary: the charging cable from the box, a
regular charging spot at home — the same shelf every evening, so
charging becomes a place as much as a chore — and a soft, dry cloth. No
cleaning fluids, no tools, no maintenance apps. The device is meant to
be looked after by a kid with a grown-up nearby, and that sets the bar
where it belongs: if caring for it needed a manual, it would be too much
care.

## Steps

The part that already works, and works carefully: **the device watches
its own battery so a kid doesn't have to.**

- When the battery gets low — around a fifth left — the device shows a
  low-battery warning. It reminds, it doesn't nag: the warning has a
  built-in pause before it can repeat.
- If the battery keeps dropping toward empty (around one in ten), the
  device doesn't just die mid-song or mid-call. It shows a shutting-down
  notice, waits a short moment, and then **switches itself off safely**,
  saving its state on the way down so it wakes up cleanly.
- **Plugging in cancels it.** If the charger goes in while the shutdown
  countdown is running, the device notices external power and calls the
  whole thing off.
- The device is deliberately cautious here: if it can't read the battery
  for some reason, it never guesses — it will not shut itself down on
  missing information.

Day to day, the screen also looks after the battery on its own: it goes
dark after a while to save power and wakes the moment the button is
pressed. There is a battery status view on the device, and the battery
gauge, charging state, and clock all come from a dedicated power module
that the device checks about twice a minute.

How software updates arrive and how to clean the device are not built
yet — the Tips and Troubleshooting below describe the proposed design
for both.

## Tips

*Proposed — the ideal design, not yet adopted.*

**Cleaning.** A soft, dry cloth handles almost everything, the canvas
included. For sticky days — jam happens — a barely damp cloth, water
only, on the shell, then dry it off. Keep liquids, wipes, and sprays
away from the speaker openings and the charging port, and never poke
anything into either.

**Storage.** Going in a drawer for a few weeks? Charge to about half,
switch it off, and pick somewhere cool and dry. Batteries age fastest
when stored completely full or completely empty — half-charged and cool
is how they nap best. Day to day the rules are shorter still: no
radiators, no summer cars, no sunny windowsills.

**Updates.** Updates look after themselves. The device fetches new
software quietly in the background, checks that it genuinely came from
us before touching anything, and installs it *next to* the software it
is already running rather than over it. At the next restart it switches
to the new version — and if anything about it is not right, it switches
straight back to the version that worked, all by itself. An update can
never leave the device stuck or half-changed, there is nothing to
approve or click, and a kid never meets an update screen mid-song.

**The routine.** Charging is a fine first responsibility: plugging in
each evening is the kid's job, like brushing teeth. The device does its
part by warning early and switching off safely instead of punishing a
forgotten evening (see Steps above).

## Troubleshooting

*Proposed — the ideal design, not yet adopted.*

**The battery drains faster than usual.** The hungriest days are call
days and low-coverage days — with weak bars, the device works harder to
stay reachable. Cold days sap batteries too, temporarily. The screen
already sleeps on its own, so the usual fix is simply a steadier spot in
the evening charging routine.

**It won't charge.** Suspect the cable and the wall adapter before the
device — cables fail far more often. Then look into the charging port
for pocket fluff and clear it gently with something soft and dry, never
anything metal.

**It feels warm while charging.** Slightly warm is normal. Hot to hold
is not: unplug it, let it cool in the open — never charge it under a
pillow or blanket — and if the heat comes back, contact us.

**It went through the wash.** It is built for a kid's life — rain,
splashes, sand at arm's length — not for a spin cycle. If it happens:
switch it off if it is still on, do not plug it in, and let it dry
thoroughly for a day or two before trying to charge. If it will not wake
up after that, get in touch.

**Something seems different after an overnight restart.** That was
probably an update installing itself. If a new version ever truly
misbehaves, the device returns to the previous one on its own — and if
it looks like that has not happened, contact us.

## Open questions

- Adopt fully automatic background updates with automatic roll-back as the only mode, or add an optional "install tonight?" approval in the yoyopod app?
- Publish concrete battery-life numbers per usage pattern, or keep the public promise qualitative until production hardware settles?
- Adopt a certified water- and dust-resistance rating for V1 “Daylight”, or ship the honest plain-language line — rain yes, washing machine no — without certifying one?
- Decide the charging connector and whether a wall adapter ships in the box before the box copy is written.

:::note[Sources]
Condensed from
[`docs/hardware/POWER_MODULE.md`](https://github.com/attmous/yoyopod/blob/main/docs/hardware/POWER_MODULE.md)
and the as-built docs site (website/ in the repository): the hardware
guide's Power Module page and the runtime guide's power worker page (the
boiler room).
:::
