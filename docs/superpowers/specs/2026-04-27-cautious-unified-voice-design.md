# Cautious Unified Voice Design

**Date:** 2026-04-27  
**Status:** Approved design for implementation planning  
**Project:** YoYoPod voice Ask and command coherence  

## Goal

Rethink the Ask and voice-command experience as one coherent YoYo voice surface while
keeping the first implementation practical on Raspberry Pi Zero 2W hardware.

This design supports `yoyo` and `hey yoyo` as spoken activation prefixes after
button-gated listening has started. It does not ship an always-listening wake-word
daemon in the first pass. The runtime should still introduce a clean wake detector
seam so a future hardware-validated backend can activate the same flow from idle or
screen-off states.

## Approved Product Direction

The selected approach is **Cautious Unified Voice**.

- The visible user-facing surface is one YoYo assistant experience.
- Button activation starts listening. The spoken phrase may include `yoyo` or `hey yoyo`,
  but the prefix is optional after activation.
- YoYoPod strips activation prefixes locally, then tries deterministic command routing.
- Confident commands win.
- Non-command phrases fall back to Ask when Ask is enabled and available.
- Mutable device data can customize command aliases, examples, thresholds, enabled flags,
  and safe allowlisted app actions.
- Always-listening wake-word support remains a future backend behind an explicit interface.

## UX Model

The UI should not expose separate "Voice Commands" and "AI Requests" modes to the child.
It should present one YoYo voice feature with familiar states:

1. Idle: YoYo is ready.
2. Listening: the device is recording speech.
3. Thinking: the runtime is transcribing and routing.
4. Reply: the device shows or speaks the outcome.

The user can say phrases such as:

- `hey yoyo call mama`
- `yoyo make it louder`
- `why is the sky blue`

The first two should route as commands when confidence is high. The last should fall
back to Ask. The reply screen may show natural outcomes such as `Calling Mama`,
`Volume`, or `Answer`, but it should not teach the child that there are two separate
apps behind the feature.

Quick-command behavior should converge with the same YoYo surface. It may still
auto-return after command outcomes, but it should not feel like a hidden second mode.

## Architecture

The new behavior belongs in the voice integration seam, not in screen code.

### Screen Layer

`AskScreen` remains presentation-focused:

- render idle/listening/thinking/reply states
- start, cancel, and repeat voice interactions
- apply navigation side effects returned by voice outcomes
- avoid parsing commands or deciding Ask fallback

### Voice Runtime

`VoiceRuntimeCoordinator` owns:

- capture and transcription flow
- TTS queue and cancellation
- interaction generation safety
- command-first routing
- Ask fallback routing
- outcome dispatch to the screen

The coordinator should use one routing path regardless of whether the transcript came
from local Vosk STT or cloud OpenAI STT. STT only converts audio to text. YoYoPod-owned
local code performs command matching.

### New Focused Pieces

Add small, testable units:

- `VoiceActivationNormalizer`: strips optional activation prefixes such as `yoyo` and
  `hey yoyo`, plus harmless leading filler where appropriate.
- `VoiceCommandDictionary`: loads built-in defaults and mutable dictionary overrides.
- `VoiceCommandRouter`: returns a typed decision: command, ask fallback, or no match.
  The decision should include confidence and a reason useful for logs/tests.
- `WakeDetector`: interface for future always-listening activation. The first
  implementation is no-op/button-gated only.

`VoiceCommandExecutor` remains responsible for side effects. It should execute only
built-in intents and safe allowlisted actions.

## Command Routing

Routing order:

1. Normalize transcript.
2. Strip optional activation prefix.
3. Match deterministic commands against the merged command dictionary.
4. If a command clears confidence, execute it.
5. If no confident command matches and Ask fallback is enabled, send the normalized
   text to Ask.
6. If Ask fallback is disabled or unavailable, return local help.

Risky actions, especially calls, should preserve confirmation behavior for ambiguous
matches. For example, a phrase like `mama please call` may ask for confirmation before
dialing.

## Configuration And Dictionary

Repo-authored config should own defaults and file paths. Mutable data should own
device-specific command customization.

Proposed config shape:

```yaml
assistant:
  activation_prefixes:
    - yoyo
    - hey yoyo
  command_routing:
    mode: command_first
    ask_fallback_enabled: true
    fallback_min_command_confidence: 0.82
  command_dictionary_path: data/voice/commands.yaml
```

Proposed mutable command dictionary:

```yaml
version: 1
intents:
  call_contact:
    aliases: [call, phone, ring]
    examples: [call mom, phone dad]
    slot: contact_name
  volume_up:
    aliases: [louder, turn it up]

actions:
  open_talk:
    aliases: [open talk, show calls]
    route: talk
```

Important boundary:

- The voice command dictionary knows command verbs, slots, examples, thresholds, and
  safe app actions.
- People/contact data knows contact display names, call targets, and nicknames.
- `hey yoyo call mama` becomes intent `call_contact` plus contact slot `mama`; contact
  lookup then resolves `mama` to the saved contact alias.

Contact aliases should live with people data, for example:

```yaml
contacts:
  - display_name: Mama
    sip_address: sip:mama@example.com
    aliases: [mama, mom, mommy]
```

Mutable command data may not define scripts, shell commands, imports, Python callables,
or arbitrary code. Invalid entries should be ignored with warnings. Built-in safe
commands should remain usable when mutable config is missing or broken.

## Safe Allowlisted Actions

The first allowlist should stay small and app-owned. Candidate actions:

- call contact through the existing contact slot flow
- play or shuffle local music
- volume up/down
- mute/unmute mic
- read screen
- open Talk
- open Listen
- open Setup
- go home or back

Actions should map to typed runtime outcomes or route names already understood by
screen routing. Dictionary entries should not directly name methods.

## Failure Handling

The user-facing behavior should be short and recoverable:

- No speech: show `I did not catch that` and allow another try.
- STT unavailable: show local/cloud speech offline feedback and keep the app running.
- Ambiguous risky command: ask for confirmation.
- Unknown phrase with Ask enabled: use Ask fallback.
- Unknown phrase with Ask disabled: return local help with a few examples.
- Invalid dictionary: log warnings and use built-in defaults.
- Future wake backend failure: disable wake activation and keep button activation.

## Testing

Add focused tests for:

- activation-prefix normalization for `yoyo`, `hey yoyo`, repeated prefixes, and
  no-prefix text
- command dictionary loading, merging, disabled intents, threshold overrides, and bad
  YAML handling
- routing decisions for command wins, Ask fallback, disabled fallback, and ambiguous calls
- allowlisted action execution and unsafe action rejection
- runtime proof that Vosk and OpenAI STT both feed the same local router
- `AskScreen` behavior proving screen code stays presentation-only

Acceptance cases:

- `hey yoyo call mama` routes to a contact call when Mama exists as a contact alias.
- `yoyo make it louder` routes to volume up.
- `hey yoyo why is the sky blue` falls back to Ask when Ask is enabled.
- Unknown phrases produce local help when Ask fallback is disabled.
- Broken mutable command config cannot disable all built-in safe commands.
- Always-on wake support is represented by an interface and config state, not an active
  background listener.

## Out Of Scope

- Always-listening wake-word backend implementation.
- Settings UI for editing the command dictionary.
- Arbitrary custom actions or scripts.
- Replacing deterministic command routing with an LLM-based command planner.
- Hardware validation of always-on wake behavior.

## Open Implementation Notes

- The existing `VoiceCommandTemplate` grammar can remain the built-in source of truth
  while the dictionary loader becomes the merge layer.
- Existing command confirmation and call/contact lookup should be preserved.
- Contact alias support may require a small people-model/data change before the
  `call mama` boundary is fully clean.
- Runtime logs should clearly distinguish STT backend, normalized transcript, routing
  decision, confidence, and final outcome without logging excessive private speech.
