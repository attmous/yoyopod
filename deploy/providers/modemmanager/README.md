# ModemManager provider input provenance

Baseline: Debian `1.24.0-1+deb13u1`, target package revision
`1.24.0-1+deb13u1+yoyopod1`, Debian trixie ARM64. No provider package is built
or installed by this input-acquisition hook. No qualified modem profile exists
at this stage.

## Resolve and verify

The native ARM `CI` workflow accepts `provider_inputs=true` for source-input
acquisition only. The coordinator dispatches an exact committed revision.
Default CI continues to build the Rust bundle. The input evidence artifact
`yoyopod-modemmanager-input-evidence-<full-sha>` transfers provenance and test
reports; it is never a deployment artifact or provider selector.

The hook obtains the official `docker.io/library/debian:trixie-slim` manifest
index and its unique Linux ARM64 child, pulls that digest, and runs:

```sh
bash build/resolve-lock.sh /evidence/source-lock.json
bash build/verify-inputs.sh /evidence/source-lock.json /evidence/verified
bash tests/test-source-lock.sh /evidence/source-lock.json
```

The build container receives only `MM_IMAGE`, `MM_IMAGE_INDEX` and
`MM_IMAGE_MANIFEST`, the authored provider directory mounted read-only, and an
evidence directory. Git credentials, host secrets and the Docker socket are
not mounted or forwarded. No host tooling or emulator is installed.

Acquisition starts with snapshot `20261006T000000Z`; if that date is still
future at execution time, it uses the previous UTC day's midnight. If the
fixed dated snapshot or exact source is unavailable, acquisition fails. It
uses apt's trusted Debian image archive keyring for the initial signed
`ca-certificates` closure over HTTP because the slim image has no CA bundle.
Archive signature, index and package hash verification stay enabled. All other
tooling and explicit input acquisition use certificate-validated HTTPS. It
then explicitly verifies InRelease, its SHA256-indexed Packages/Sources bytes,
the descriptor's maintainer signature with `debian-keyring.gpg`, and all source
archives. Only the fixed historical snapshot relaxes Release expiry.

The dependency lock records the entire installed closure, including bootstrap
tools and image packages, from signed ARM64/all Packages entries. Acquisition
fails if any installed version cannot be found uniquely in that snapshot.
The actual extracted Debian control file drives `apt-get build-dep`; GCC,
Meson, dpkg, keyring bytes, signer fingerprints and image manifest hashes are
recorded. `acquisition/bootstrap.txt` records the bootstrap snapshot, trusted
archive keyring and CA bundle hashes and installed certificate closure; the
signed dependency lock includes the exact certificate package versions/hashes.
`SOURCE_DATE_EPOCH` comes from the Debian source changelog. The stock
Debian quilt series remains in the authenticated Debian source archive.
`patches` starts empty; later tasks must add real local patch paths/hashes.

Each signed metadata/source record keeps `request_uri` for its fixed dated
snapshot path and `uri` for the actual final HTTPS download URI, including
snapshot's content-addressed `/file/<hash>/<name>` redirects. Validation binds
the request to the recorded snapshot, restricts the final URI to the official
snapshot origin/path, verifies all SHA256 bytes and rejects further changed
redirects. Signed Release/Sources indexes authenticate the original paths.

Validation rejects unknown fields and absent/invalid pins before fetching.
It checks the executing image evidence, keyrings, signed indexes, actual
descriptor signer and dependency closure, then fetches and checks every locked
source and dependency archive. Cached bytes are always rechecked. Source is
reconstructed only after verification; previous modified source is replaced.
Tests mutate a real resolved candidate, invoke the real validator and require
nonzero status without a staged source directory for every invalid candidate.

## Resolution status

The first native acquisition is pending. No placeholder source lock is
committed. Actual resolution values, signatures and behavioral test results
must be reviewed before accepting this task or adding provider build work.
