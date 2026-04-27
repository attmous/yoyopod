# Offline STT / Vosk Model Lifecycle

This document is the source of truth for how YoYoPod keeps, drops, and
measures offline Vosk speech-to-text models.

## Current lifecycle

- `VoiceRuntimeCoordinator` keeps one cached `VoiceService` for the current
  `VoiceSettings`.
- `VoiceService` uses `VoskSpeechToTextBackend` by default for offline STT.
- `VoskSpeechToTextBackend` retains at most one loaded Vosk model path per
  backend instance.
- When runtime settings change enough to require a new `VoiceService`, the old
  service explicitly clears its STT backend cache before replacement.

That makes the supported steady-state path explicit:

- one runtime voice service
- one Vosk backend under that service
- zero or one retained Vosk model under that backend

## Config knob

`config/voice/assistant.yaml` now exposes:

```yaml
assistant:
  vosk_model_keep_loaded: true
```

Equivalent env var:

```bash
YOYOPOD_VOSK_MODEL_KEEP_LOADED=true
```

Behavior:

- `true` keeps the currently selected Vosk model loaded after first use. This is
  the latency-optimized default and matches the current voice product direction.
- `false` loads the model for each transcription request and drops the backend's
  retained reference immediately afterward. This is a best-effort lower-idle-RAM
  mode, not a hard RSS guarantee.

## Measured footprint

Measurements below were captured from this repo checkout with the tracked small
English model at `models/vosk-model-small-en-us`.

### Storage

Command:

```bash
du -sh models/vosk-model-small-en-us
du -sk models/vosk-model-small-en-us
find models/vosk-model-small-en-us -type f | wc -l
```

Observed result:

- on-disk size: `68M`
- on-disk size (KiB): `69300`
- tracked files in the model directory: `14`

### Process memory

Command summary:

- baseline Python process
- import `vosk`
- construct `vosk.Model("models/vosk-model-small-en-us")`
- delete the Python reference and run `gc.collect()`
- read `VmRSS` and `VmSize` from `/proc/self/status`

Observed result:

| Stage | VmRSS | VmSize |
| --- | ---: | ---: |
| before import | 14,000 kB | 28,380 kB |
| after `from vosk import Model` | 39,008 kB | 54,620 kB |
| after `Model(...)` | 157,576 kB | 2,075,196 kB |
| after `del model; gc.collect()` | 89,488 kB | 2,000,164 kB |

Practical takeaway:

- the shipped small model is already a meaningful storage payload on disk
- loading it in-process raised RSS by roughly `118 MB` in this environment
- dropping Python references recovered some memory, but did not return the
  process to its pre-load baseline

That is why `vosk_model_keep_loaded=false` is documented as best effort only.
For a long-lived process, clearing the cache removes YoYoPod's retained model
reference, but native allocator behavior can still leave RSS above baseline.

## Operational guidance

- Leave `vosk_model_keep_loaded=true` when fast repeated voice interactions are
  more important than idle-memory pressure.
- Consider `false` only on constrained hardware where voice commands are used
  infrequently and reload latency is acceptable.
- Do not expect `false` to behave like a hard memory cap. It bounds YoYoPod's
  retained model references; it does not force the OS to reclaim all native
  allocations immediately.
