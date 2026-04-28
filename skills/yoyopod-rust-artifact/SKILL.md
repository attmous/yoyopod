---
name: yoyopod-rust-artifact
description: Deploy and test Rust binaries from GitHub Actions artifacts instead of building on Raspberry Pi
disable-model-invocation: true
allowed-tools:
  - Read
  - Bash(git status:*)
  - Bash(git branch --show-current:*)
  - Bash(git rev-parse:*)
  - Bash(git push:*)
  - Bash(gh run:*)
  - Bash(gh pr:*)
  - Bash(mkdir:*)
  - Bash(chmod:*)
  - Bash(ssh:*)
  - Bash(scp:*)
  - Bash(yoyopod remote:*)
---

## Rule

Rust binaries for hardware validation must come from GitHub Actions artifacts
for the exact commit being tested. Do not run `cargo build`,
`yoyopod build rust-ui-poc`, or any other Rust compile on the Raspberry Pi Zero
2W unless the user explicitly overrides this rule.

Native C shim work is different: `yoyopod remote sync --clean-native` may still
rebuild the LVGL/Liblinphone C shims on the Pi when native/CMake inputs change.

## Current Artifact

The current Rust UI PoC artifact is:

```bash
yoyopod-rust-ui-poc-<sha>
```

It contains the ARM64 Linux binary that should be installed at:

```bash
/opt/yoyopod-dev/checkout/workers/ui/rust/build/yoyopod-rust-ui-poc
```

## Rust VoIP Host Artifact

The Rust VoIP Host artifact is:

```bash
yoyopod-voip-host-<sha>
```

Install it at:

```bash
/opt/yoyopod-dev/checkout/src/crates/voip-host/build/yoyopod-voip-host
```

Do not build `yoyopod-voip-host` on the Raspberry Pi Zero 2W.

## Steps

1. **Check local git status.** Run `git status --short`. If there are local
   changes, commit them first or stop and ask the user whether this is a
   dirty-tree exception.

2. **Resolve branch and commit.**

   ```bash
   git branch --show-current
   git rev-parse HEAD
   ```

3. **Push the commit.** Run `git push`. If there is no upstream, run
   `git push -u origin <branch>`.

4. **Find the successful CI run for the exact commit.**

   ```bash
   gh run list --workflow CI --branch <branch> --json databaseId,headSha,status,conclusion --limit 20
   ```

   Use only a run whose `headSha` equals the commit from step 2 and whose
   conclusion is `success`. If the run is still queued or in progress, wait.
   If it failed, inspect the failed job before hardware deploy.

5. **Download the artifact locally.**

   ```bash
   mkdir -p .artifacts/rust-ui/<sha>
   gh run download <run-id> --name yoyopod-rust-ui-poc-<sha> --dir .artifacts/rust-ui/<sha>
   chmod +x .artifacts/rust-ui/<sha>/yoyopod-rust-ui-poc
   ```

6. **Make sure the Pi dev checkout is on the same commit.**

   ```bash
   yoyopod remote mode activate dev
   yoyopod remote sync --branch <branch>
   ```

   Add `--clean-native` only when native C/CMake/shim inputs changed.

7. **Install the CI-built Rust binary on the Pi.**

   ```bash
   ssh <user>@<host> 'mkdir -p /opt/yoyopod-dev/checkout/workers/ui/rust/build'
   scp .artifacts/rust-ui/<sha>/yoyopod-rust-ui-poc <user>@<host>:/opt/yoyopod-dev/checkout/workers/ui/rust/build/yoyopod-rust-ui-poc
   ssh <user>@<host> 'chmod +x /opt/yoyopod-dev/checkout/workers/ui/rust/build/yoyopod-rust-ui-poc'
   ```

8. **Run the Rust UI hardware command from the Pi checkout.** For Whisplay hub
   validation:

   ```bash
   ssh <user>@<host> 'cd /opt/yoyopod-dev/checkout && YOYOPOD_WHISPLAY_DC_GPIO=27 YOYOPOD_WHISPLAY_RESET_GPIO=4 YOYOPOD_WHISPLAY_BUTTON_GPIO=17 YOYOPOD_WHISPLAY_BUTTON_ACTIVE_LOW=0 LD_LIBRARY_PATH=/opt/yoyopod-dev/checkout/yoyopod/ui/lvgl_binding/native/build/lvgl/lib:/opt/yoyopod-dev/checkout/yoyopod/ui/lvgl_binding/native/build:$LD_LIBRARY_PATH /opt/yoyopod-dev/venv/bin/python -m yoyopod_cli.main pi rust-ui-poc --worker workers/ui/rust/build/yoyopod-rust-ui-poc --screen hub --hub-renderer lvgl --frames 1'
   ```

9. **Report exact provenance.** Include the branch, commit SHA, CI run ID,
   artifact name, Pi host, command result, and whether the dev service was left
   running.
