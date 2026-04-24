# Release Process

YoYoPod now uses one explicit release contract:

- package version source: `yoyopod/_version.py`
- release tag format: `vMAJOR.MINOR.PATCH`
- release artifacts: Python package distributions, full repo bundles, and an ARM64 slot tarball
- release automation: `.github/workflows/release.yml`

## Versioning

YoYoPod uses semantic versioning:

- `major` for breaking or externally visible contract changes
- `minor` for backward-compatible feature releases
- `patch` for backward-compatible fixes and polish

Check the current version:

```bash
uv run yoyopod release current
```

Bump the version source:

```bash
uv run yoyopod release bump patch
uv run yoyopod release bump minor
uv run yoyopod release bump major
```

Or set it explicitly:

```bash
uv run yoyopod release set-version 0.2.0
```

## Local Release Build

Build the release artifacts locally:

```bash
uv run yoyopod release build
```

That command builds:

- Python wheel
- Python source distribution
- full repo bundle as `.tar.gz`
- full repo bundle as `.zip`
- `release-metadata.json`
- `SHA256SUMS.txt`

By default it refuses to build from a dirty tracked worktree. For local-only experiments, you can override that:

```bash
uv run yoyopod release build --allow-dirty
```

## GitHub Release Pipeline

The release workflow runs on:

- push of a tag like `v0.2.0`
- manual dispatch with an existing release tag

The workflow:

1. checks out the tagged revision
2. installs the dev environment with `uv`
3. runs `uv run python scripts/quality.py gate`
4. runs `uv run pytest -q`
5. runs `uv run yoyopod release build --check-tag <tag>`
6. builds a Linux ARM64 self-contained slot artifact via `deploy/docker/slot-builder.Dockerfile`
7. uploads the built artifacts
8. creates or updates the matching GitHub Release

On pull requests, the expensive ARM64 slot build is label-gated. Add the
`build-arm-slot` label when you need a PR commit to produce a slot artifact.
Normal PR commits still run the `quality` and `test` jobs, but they skip the
roughly 20-minute ARM builder unless that label is present. Tagged releases and
`main` pushes continue to build the ARM64 slot automatically.

The published ARM64 slot artifact is intended to be installed directly under
`/opt/yoyopod-prod/releases/<version>/` and consumed by:

- `deploy/scripts/install_release.sh`
- `yoyopod remote release install-url <artifact-url>`

## Recommended Release Flow

1. Bump the version:

   ```bash
   uv run yoyopod release bump patch
   ```

2. Run the repo gates:

   ```bash
   uv run python scripts/quality.py gate
   uv run pytest -q
   ```

3. Commit and merge the version bump.
4. Tag the release from the merged commit:

   ```bash
   git tag v0.1.1
   git push origin v0.1.1
   ```

5. Let the release workflow build and publish the artifacts.

## Notes

- The Python package artifacts are useful for packaging and inspection.
- The repo bundles are the more complete release asset for hardware-oriented YoYoPod workflows because they include the broader repo surface the device and deploy tooling rely on.
- The ARM64 slot tarball is the OTA-style deploy asset. It already contains the
  bundled config tree, native `.so` shims, launcher, manifest, and slot-local
  runtime venv expected by the slot installer.
- The slot tarball is published with a `.sha256` sidecar for the archive bytes.
  The embedded `manifest.json` records the unpacked slot payload digest instead
  of the digest of the tarball that contains the manifest.
