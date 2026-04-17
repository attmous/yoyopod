# Technical Priorities for YoyoPod_Core

This is the translation layer from product truth to engineering reality.

## Priority 0: Stop treating V1 like a platform
YoyoPod_Core should optimize for a reliable appliance, not an extensible universe.

Implications:
- kill or defer anything that smells like framework-building for future features
- keep Ask/AI behind the main trust-critical flows
- prefer boring, testable paths over elegant abstractions that buy nothing for V1

## Priority 1: Make calling brutally reliable
Calling is one of the two trust anchors. If it flakes, the product story collapses.

Engineering focus:
- inbound call reliability
- outbound call reliability
- reconnect behavior after weak/returning network
- call audio stability over time
- call-state correctness in UI and runtime
- fast recovery from VoIP backend weirdness
- clean failure states instead of silent limbo

What this means in code:
- instrument the VoIP lifecycle heavily
- reduce hidden state transitions
- verify keep-alive/reconnect behavior on real hardware and real networks
- build repeatable call soak tests, not just happy-path tests
- treat every "call stuck," "ringing but dead," or "UI says one thing / backend says another" bug as top-tier

## Priority 2: Make live location trustworthy
Not fancy map feature. Trustworthy.

Engineering focus:
- stable GPS acquisition
- sane update cadence
- timestamp freshness
- clear stale-location handling
- robust 4G uplink path for reporting
- parent-facing semantics: last seen, current confidence, last successful fix

What this means in code/system design:
- location data needs freshness metadata everywhere
- never present stale data as current
- connectivity loss must degrade honestly
- geofencing is secondary to "where is the device right now, roughly, and when was that last updated?"
- build logging around fix quality, send frequency, and upload failures

## Priority 3: Eliminate freezes and UI deadness on hardware
This is the current product killer in disguise.

Engineering focus:
- remove or isolate blocking work from hot UI/runtime paths
- identify real freeze sources on Pi hardware
- reduce rendering churn
- reduce event-loop or coordinator overload
- make the system recoverable if a component stalls

What this means in practice:
- profile on target hardware, not your imagination
- add watchdog-style detection for stalled UI/runtime loops
- log slow operations with timestamps and subsystem tags
- stress-test navigation while music and VoIP subsystems are active
- if a flow can freeze the device, that bug outranks almost every feature request

## Priority 4: Preserve the one-button interaction contract
Your input model is part of the product identity. If it feels inconsistent, the device feels dumb.

Engineering focus:
- tap/double/hold timing consistency
- no ambiguous actions
- no mode confusion around PTT/Ask/back behavior
- screen-specific input mode changes must stay predictable
- fast visual/audio feedback after input

What this means in code:
- centralize and test one-button grammar transitions
- validate timing thresholds on real hardware with actual human use
- avoid layering hidden exceptions on top of the grammar
- ensure Ask quick-command and navigation mode never feel like conflicting personalities

## Priority 5: Make audio always feel available
Music is not just a feature. It is the daily habit-forming use case.

Engineering focus:
- fast playback start
- no broken playback after navigation or calls
- clear interruption/resume rules
- no weird volume state drift
- stable local media indexing and retrieval

What this means:
- audio interruption policy must be deterministic
- call/audio handoff should be tested constantly
- local playback should work even when connectivity is bad
- playback state should survive routine UI movement without getting lost

## Priority 6: Build the parent-app contract now, even if the app itself lags
The device is only half the product. The parent app is the other half.

Engineering focus:
- define clean backend contracts for contacts, whitelist rules, location updates, device settings, and message history
- don’t let device-side hacks hardcode assumptions that make the parent app miserable later
- model parent-managed state clearly and minimally

Strong opinion:
if the device code grows faster than the parent control model, you’re building half a product and congratulating yourself for it.

## Priority 7: Design for degraded connectivity, but don’t overbuild fallback yet
You already said fallback is undecided and maybe not V1. Good. Keep it that way unless it becomes crisp.

Engineering focus:
- detect loss of network cleanly
- retry sanely
- preserve local functionality
- report degraded state honestly
- queue what is reasonable to queue

But:
- do not burn weeks on speculative SMS-like fallback fantasies without a tight product definition
- first make the primary online path dependable

## Priority 8: Battery and thermal behavior must be measured, not hoped for
"One day battery" is a product requirement, not a motivational quote.

Engineering focus:
- measure idle drain
- measure playback drain
- measure standby with location updates
- measure call drain
- measure worst-case radio/audio/screen behavior
- enforce screen and subsystem power policies

Translation:
if you cannot characterize power consumption by mode, you do not have a battery strategy, you have a prayer circle.

## Priority 9: Industrial-design constraints should shape software decisions earlier
Since hardware industrial design is your hardest open problem, software should stop assuming infinite room and ideal inputs.

Engineering focus:
- tiny-screen UX discipline
- low-button-count discipline
- speaker/mic constraints
- boot/recovery UX
- charging/power-state clarity
- is this carryable and understandable over debug convenience

## Priority 10: Product-grade observability on hardware
You need to know what happened without guessing.

Must-have telemetry/logging areas:
- boot and shutdown
- connectivity transitions
- GPS fix state and send attempts
- VoIP register/call lifecycle
- audio backend lifecycle
- screen transitions
- input events and timing
- freeze/stall warnings
- battery and thermal snapshots

This is not optional.
Without this, hardware debugging turns into folklore.

## What should be deprioritized
These are not dead forever. Just not allowed to steal oxygen.

Deprioritize for now:
- ambitious Ask/LLM expansion
- fancy geofence behaviors beyond the basics
- deep customization
- broad contact/messaging models beyond whitelist family-safe flows
- architectural refactors that don’t directly improve reliability, clarity, or testability
- polished extras before parent trust flows are solid

## Suggested engineering order
1. Freeze investigation and runtime stability on hardware
2. VoIP reliability under real-world network conditions
3. Location freshness/trust model and reporting path
4. Audio/call interruption and resume correctness
5. One-button interaction validation on real hardware
6. Parent-app-facing backend contract cleanup
7. Battery characterization and power tuning
8. Only then broaden feature scope

## Governing rule for YoyoPod_Core
Every engineering decision should answer:
Does this improve trust, reliability, simplicity, or daily usefulness for V1?

If not, it’s probably a distraction wearing a nice jacket.
