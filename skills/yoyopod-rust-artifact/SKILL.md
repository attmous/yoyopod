---
name: yoyopod-rust-artifact
description: Deploy and test Rust runtime/worker binaries from GitHub Actions artifacts instead of building on Raspberry Pi
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
`yoyopod build rust-runtime`, `yoyopod build rust-ui-host`,
`yoyopod build rust-ui-poc`, or any other Rust compile on the Raspberry Pi
Zero 2W unless the user explicitly overrides this rule.

Native C shim work is different only for LVGL:
`yoyopod remote sync --clean-native` may still rebuild the LVGL C shim on the
Pi when native/CMake inputs change.

## Current Rust Artifact Contract

Use the artifact whose suffix equals the exact commit under test, not a pull
request merge SHA.

The CI artifact is:

```bash
yoyopod-rust-device-arm64-<sha>
```

It contains:

```bash
yoyopod-rust-device-arm64-<sha>.tar.gz
```

That tarball extracts an install-ready `device/.../build/...` tree:

| Path inside extracted tree | Purpose |
| --- | --- |
| `device/runtime/build/yoyopod-runtime` | Top-level Rust runtime entrypoint when `YOYOPOD_DEV_RUNTIME=rust`. |
| `device/ui/build/yoyopod-ui-host` | Whisplay UI worker and LVGL renderer. |
| `device/media/build/yoyopod-media-host` | Rust media/mpv worker. |
| `device/voip/build/yoyopod-voip-host` | Rust Liblinphone/SIP worker. |
| `device/network/build/yoyopod-network-host` | Rust SIM7600/PPP/GPS worker. |

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

5. **Download and extract the Rust device bundle locally.**

   ```bash
   mkdir -p .artifacts/rust-device/<sha>
   gh run download <run-id> --name yoyopod-rust-device-arm64-<sha> --dir .artifacts/rust-device/<sha>
   tar -xzf .artifacts/rust-device/<sha>/yoyopod-rust-device-arm64-<sha>.tar.gz -C .artifacts/rust-device/<sha>
   chmod +x .artifacts/rust-device/<sha>/device/runtime/build/yoyopod-runtime
   chmod +x .artifacts/rust-device/<sha>/device/ui/build/yoyopod-ui-host
   chmod +x .artifacts/rust-device/<sha>/device/media/build/yoyopod-media-host
   chmod +x .artifacts/rust-device/<sha>/device/voip/build/yoyopod-voip-host
   chmod +x .artifacts/rust-device/<sha>/device/network/build/yoyopod-network-host
   ```

6. **Make sure the Pi dev checkout is on the same commit.**

   ```bash
   yoyopod remote mode activate dev
   yoyopod remote sync --branch <branch> --sha <sha>
   ```

   Add `--clean-native` only when native C/CMake/shim inputs changed.

7. **Install the CI-built Rust binaries on the Pi.**

   ```bash
   scp .artifacts/rust-device/<sha>/yoyopod-rust-device-arm64-<sha>.tar.gz <user>@<host>:/tmp/yoyopod-rust-device-arm64-<sha>.tar.gz
   ssh <user>@<host> 'cd /opt/yoyopod-dev/checkout && tar -xzf /tmp/yoyopod-rust-device-arm64-<sha>.tar.gz && chmod +x device/runtime/build/yoyopod-runtime device/ui/build/yoyopod-ui-host device/media/build/yoyopod-media-host device/voip/build/yoyopod-voip-host device/network/build/yoyopod-network-host'
   ```

8. **Select the Rust dev-lane owner and restart.** The dev service still has a
   Python fallback, so set the override before testing the Rust entrypoint:

   ```bash
   ssh <user>@<host> 'set -e; sudo touch /etc/default/yoyopod-dev; if sudo grep -q "^YOYOPOD_DEV_RUNTIME=" /etc/default/yoyopod-dev; then sudo sed -i "s/^YOYOPOD_DEV_RUNTIME=.*/YOYOPOD_DEV_RUNTIME=rust/" /etc/default/yoyopod-dev; else printf "%s\n" "YOYOPOD_DEV_RUNTIME=rust" | sudo tee -a /etc/default/yoyopod-dev >/dev/null; fi'
   yoyopod remote restart
   ```

9. **Validate the Rust path.**

   ```bash
   yoyopod remote validate --branch <branch> --sha <sha> --with-rust-ui-host --with-lvgl-soak
   ```

   For a direct UI worker check, run from the Pi checkout:

   ```bash
   ssh <user>@<host> 'cd /opt/yoyopod-dev/checkout && YOYOPOD_WHISPLAY_DC_GPIO=27 YOYOPOD_WHISPLAY_RESET_GPIO=4 YOYOPOD_WHISPLAY_BUTTON_GPIO=17 YOYOPOD_WHISPLAY_BUTTON_ACTIVE_LOW=0 LD_LIBRARY_PATH=/opt/yoyopod-dev/checkout/yoyopod/ui/lvgl_binding/native/build/lvgl/lib:/opt/yoyopod-dev/checkout/yoyopod/ui/lvgl_binding/native/build:$LD_LIBRARY_PATH /opt/yoyopod-dev/checkout/device/ui/build/yoyopod-ui-host --hardware whisplay'
   ```

10. **Report exact provenance.** Include the branch, commit SHA, CI run ID,
    artifact names, Pi host, active runtime owner, command result, and whether
    the dev service was left running.
