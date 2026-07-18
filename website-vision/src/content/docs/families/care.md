---
title: Charging & Care
description: Battery life, charging, cleaning, and keeping it healthy.
---

*Keep the device charged, clean, updated, and out of the washing machine.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## What you'll need

*Placeholder — no as-built content yet.*

- The charging cable from the box (connector type TBD)
- A regular charging spot at home — same place every evening
- A soft, dry cloth for cleaning

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

What is *not* written yet, honestly: how software updates arrive and
install, and cleaning guidance. Those stay in the placeholder sections
below until there is something real to say.

## Tips

*Placeholder — no as-built content yet.*

- Kids own the routine: charging the device is their job, like brushing teeth
- Water, sand, and washing machines: what the device tolerates (rating TBD) — and what it doesn't
- Heat and cold: don't leave it on radiators or in summer cars
- Low-battery behavior: what the device does to keep calls and location alive longest (TBD)

## Troubleshooting

*Placeholder — no as-built content yet.*

- Battery drains faster than expected — what eats power and what to check
- Device won't charge — cable, port, and power-source checks
- Device feels warm while charging — what's normal, what isn't
- It went through the wash — honest guidance on what to do next (TBD)

## Open questions

- TODO: Real-world battery life targets per usage pattern, and what we promise publicly
- TODO: Charging connector and whether a wall adapter ships in the box
- TODO: Any water/dust ingress rating for the production device, or none for V1?
- TODO: Update policy — automatic overnight, parent-approved, or both?

:::note[Sources]
Condensed from
[`docs/hardware/POWER_MODULE.md`](https://github.com/attmous/yoyopod/blob/main/docs/hardware/POWER_MODULE.md)
and the as-built docs site (website/ in the repository): the hardware
guide's Power Module page and the runtime guide's power worker page (the
boiler room).
:::
