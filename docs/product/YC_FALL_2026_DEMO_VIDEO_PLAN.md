# YC Fall 2026 demo video plan

## Objective

Produce a 70-second founder-led product demo that proves yoyopod exists, works on real hardware, and solves one clear problem:

> Give a child family connection and audio without handing them a smartphone.

This is a YC demo, not a lifestyle commercial. Show the working prototype immediately. Use a video generation model as an editor and for restrained transitions, cleanup, captions, and shot extension. Do not use it to fabricate product behavior.

## Hard rules for the video model

- Use real footage for every product interaction.
- Preserve the real prototype, screen geometry, UI, button placement, and response timing.
- Never generate fake UI text, fake calls, fake location data, or features that were not recorded working.
- Do not present the V2 enclosure renders as shipped hardware. They are an industrial-design study.
- Do not claim live location, a parent mobile app, Ask AI, school mode, or production readiness.
- Avoid glossy launch-film language, stock-footage families, cinematic children, fake testimonials, dramatic music, and impossible camera moves.
- Keep cuts simple and fast. The founder voice and product sounds should carry the video.
- Use lowercase `yoyopod` everywhere.
- Format: 16:9, 1920x1080, 24 or 30 fps, natural color, clean dialogue, burned-in captions.
- Target runtime: 68–72 seconds.

## Required source footage

Record these before handing the project to the generation/editing model:

1. Founder speaking directly to camera while holding the real prototype.
2. Clean three-quarter and side-button close-ups of the real prototype.
3. Unbroken footage of opening Listen and starting a real podcast or local audio item.
4. Unbroken footage of placing a real family call from the Talk screen.
5. Unbroken footage of recording and delivering a real voice note, plus the recipient receiving it.
6. Founder closing to camera with the powered-on prototype.
7. Clean screen captures or stills of the Hub, Listen, and Talk screens for compositing only when the physical display is unreadable on camera.

Use these repository assets only as references:

- `docs/assets/readme/yoyopod-device-tour.gif` — current UI behavior
- `docs/assets/readme/hub.png` — Hub UI
- `docs/assets/readme/listen.png` — Listen UI
- `docs/assets/readme/talk.png` — Talk UI
- `docs/hardware/enclosure/v2/colorways/render-tangerine.png` — future enclosure study; do not substitute it for the prototype
- `docs/product/PRODUCT_VIDEO.mp4` — silent enclosure concept footage; optional two-second end-card background only, labeled `industrial design concept`

## Six-shot plan

### Shot 1 — Why it exists

**Time:** 0:00–0:09<br>
**Source:** Real founder footage<br>
**Framing:** Medium close-up, eye level, quiet room, prototype already visible in the founder's hand. No animated logo intro.

**Founder dialogue:**

> I'm Moustafa. I built yoyopod because I wanted my son to call us, send voice notes, and listen to his podcasts without giving him a smartphone.

**On-screen text:**

`yoyopod`<br>
`the first device before a smartphone`

**Model instruction:**

> Open directly on the founder speaking to camera in a real home or workshop. Keep the handheld prototype visible from the first frame. Use natural window light, a locked camera, realistic skin texture, and clean production audio. Add restrained lowercase captions. Do not beautify or redesign the device. Do not insert family stock footage.

### Shot 2 — Prove the hardware is real

**Time:** 0:09–0:20<br>
**Source:** Real macro footage and one continuous interaction<br>
**Framing:** Three-quarter close-up. The founder wakes the device, shows the 240x280 screen, and presses the physical side button.

**Voiceover:**

> This is the working prototype. It runs on a Raspberry Pi Zero 2W with a tiny screen, a speaker, a microphone, and one physical side button.

**On-screen text:**

`working prototype`<br>
`Pi Zero 2W · small screen · physical controls`

**Model instruction:**

> Cut from the founder to a real macro shot of the powered-on prototype. Preserve all scratches, seams, proportions, display refresh, and button travel. Show one human hand pressing the real side button. Keep the background plain and the movement slow enough to inspect the hardware. Do not replace the prototype with the V2 enclosure render.

### Shot 3 — Listen flow

**Time:** 0:20–0:32<br>
**Source:** Real unbroken device footage<br>
**Framing:** Over-the-hand close-up with the screen readable. Show Hub to Listen to a real audio item playing.

**Voiceover:**

> He can open Listen, choose one of his podcasts or local audio files, and play it without borrowing a parent's phone.

**Production audio:**

Keep one second of the real button sound and speaker playback under the voiceover. Use royalty-cleared or founder-owned audio.

**On-screen text:**

`podcasts and local audio`

**Model instruction:**

> Use the complete real interaction take. Do not shorten the UI response so much that it looks fabricated. If the physical screen is hard to read, corner-pin the supplied real screen capture onto the display while preserving the hand, reflections, bezel, and timing. Never generate replacement UI labels or album art.

### Shot 4 — Real family call

**Time:** 0:32–0:45<br>
**Source:** Real unbroken call footage<br>
**Framing:** Start on the Talk screen, show contact selection, connecting state, and the recipient answering on a separate real phone. A simple split screen is allowed after connection.

**Voiceover:**

> From Talk, he can call his mother directly. The point is simple: family communication without an open phone in his pocket.

**Live dialogue:**

Child or founder through yoyopod: `Hi, can you hear me?`<br>
Recipient: `Yes, I can hear you.`

**On-screen text:**

`family calls`

**Model instruction:**

> Preserve the real call setup and connection. Show the actual Talk UI and actual receiving phone. Use a clean split screen only after the call connects. Keep the live two-line exchange audible. Do not generate a contact name, connection badge, waveform, or phone screen that was not captured.

### Shot 5 — Voice note flow

**Time:** 0:45–0:57<br>
**Source:** Real recording and delivery footage<br>
**Framing:** Close-up of holding the physical button, recording a short note, releasing, then the recipient receiving or playing the note.

**Live dialogue:**

> Mum, I'm heading home now.

**Voiceover after delivery:**

> He already uses the prototype for voice notes, calls, and podcasts. Those are real behaviors, not features we invented for a pitch.

**On-screen text:**

`voice notes`<br>
`already used at home`

**Model instruction:**

> Match-cut the button release to the recipient notification or playback. Preserve the real recorded voice and delivery timing. Keep the edit factual and quiet. Do not add fake delivery ticks, maps, GPS indicators, or safety claims.

### Shot 6 — What happens next

**Time:** 0:57–1:10<br>
**Source:** Real founder close plus optional two-second labeled enclosure concept<br>
**Framing:** Founder back to camera, holding the powered-on prototype. End on the device and wordmark.

**Founder dialogue:**

> Next, we're putting yoyopod in the hands of five families in Stuttgart. We want to prove that kids choose to carry it and parents choose it instead of a first smartphone.

**End card:**

`yoyopod`<br>
`the first device before a smartphone`<br>
`Stuttgart, Germany`

Optional small footer:

`working prototype · first family pilot next`

**Model instruction:**

> Return to the same founder framing as shot one. Keep the prototype powered on and visible. End with a simple lowercase yoyopod wordmark on a warm neutral background. If the V2 enclosure render appears, limit it to the final two seconds and label it `industrial design concept`. Do not use a fake purchase CTA, waitlist counter, customer count, or shipping date.

## Complete narration script

> I'm Moustafa. I built yoyopod because I wanted my son to call us, send voice notes, and listen to his podcasts without giving him a smartphone.
>
> This is the working prototype. It runs on a Raspberry Pi Zero 2W with a tiny screen, a speaker, a microphone, and one physical side button.
>
> He can open Listen, choose one of his podcasts or local audio files, and play it without borrowing a parent's phone.
>
> From Talk, he can call his mother directly. The point is simple: family communication without an open phone in his pocket.
>
> Mum, I'm heading home now.
>
> He already uses the prototype for voice notes, calls, and podcasts. Those are real behaviors, not features we invented for a pitch.
>
> Next, we're putting yoyopod in the hands of five families in Stuttgart. We want to prove that kids choose to carry it and parents choose it instead of a first smartphone.

## Master prompt for the video generation/editing model

> Assemble a 70-second, 16:9 YC product demo for yoyopod from the supplied real founder, hardware, screen, call, and voice-note footage. The tone is direct, credible, warm, and technical. This is evidence for investors, not a glossy consumer advertisement. Open on the founder and working prototype immediately. Preserve real product geometry, UI, timing, audio, and imperfections. Use simple cuts, occasional restrained punch-ins, natural color, clean dialogue, low or no music, and accurate burned-in captions. Follow the six-shot plan and narration exactly. Never fabricate product behavior, contacts, messages, metrics, users, location data, mobile apps, AI features, or production readiness. Keep `yoyopod` lowercase. End on `the first device before a smartphone` and `Stuttgart, Germany`.

## Global negative prompt

> No futuristic holograms, no generic child-tech commercial, no fake happy-family montage, no glossy Apple-style product replacement, no invented UI, no misspelled screen text, no touch-screen gestures, no camera on the device, no smartphone-shaped yoyopod, no smartwatch form factor, no live map, no AI avatar, no school scene, no social media, no shipping claim, no customer-count claim, no fake testimonial, no dramatic orchestral trailer music, no lens flares, no impossible floating product, no capitalized YOYOPOD.

## Edit and delivery checklist

- The real prototype appears within the first second.
- Each core action is visible in one unbroken take before any cutaway.
- The call includes an audible real response.
- The voice note is recorded and received on camera.
- Captions match the spoken words exactly.
- Music, if any, stays at least 18 dB below dialogue.
- Every product claim is shown or explicitly framed as the next pilot step.
- The video still makes sense with sound muted.
- Export one clean version and one version with burned-in English captions.
- Watch the final export on a phone and a laptop before submission.
