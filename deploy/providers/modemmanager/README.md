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
snapshot's content-addressed `/file/<hash>/<name>` redirects. Validation requires
the exact release/ARM64 Packages/Sources request paths for each metadata kind
and binds the descriptor metadata request/final URI/hash to its source entry.
It reissues every original dated request over HTTPS, verifies the response
SHA256 and effective URI against the pins, and checks those same bindings on
cache hits. Editable URI sidecars cannot authorize the relationship. The final
URI is restricted to the official snapshot origin/path; signed Release/Sources
indexes authenticate the index and source paths.

Successful archive `gpgv` verification may yield multiple legitimate signers.
The scalar archive signer pin is the lexicographically first fingerprint in
the nonempty freshly verified set, sorted with the C locale. Acquisition and
validation recompute the same policy; full signature statuses/fingerprint sets
are retained in the evidence and signature report. Descriptors separately
require exactly one verified signer. No failed signature is ignored.

Validation rejects unknown fields and absent/invalid pins before fetching.
It checks the executing image evidence, keyrings, signed indexes, actual
descriptor signer and dependency closure, then fetches and checks every locked
source and dependency archive. Cached bytes are always rechecked. Source is
reconstructed only after verification; previous modified source is replaced.
Tests mutate a real resolved candidate, invoke the real validator and require
nonzero status without a staged source directory for every invalid candidate.
They include altered per-kind/descriptor paths, coordinated snapshot/request
prefix changes, valid cached reconstruction and invalid cached provenance.

Before native lock acquisition, focused regressions may run with a genuine
dated InRelease and the archive keyring extracted from the digest-pinned image:

```sh
bash tests/test-source-lock.sh --archive-signature KEYRING INRELEASE EXPECTED_SIGNER
bash tests/test-source-lock.sh --request-provenance KEYRING INRELEASE REQUEST_URI FINAL_URI
```

These exercise actual gpgv and the validator's actual HTTPS/cache helper. They
do not substitute for the native positive lock and full mutation suite.

## Validated literal inputs

[Native CI run 37394089751](https://github.com/attmous/yoyopod/actions/runs/37394089751)
passed on exact checkout `1b29d51decb1367e89eb093b6353b5abfd491159`.
The tracked `source-lock.json` is a byte-for-byte copy of its validated output,
SHA256 `0d304d4b12c3505bcba9d55cc8cd18d2f459f76eafe7031ffcce334f9bc79a6f`.
The run executed the three resolver/validator/full-suite commands above. It
passed positive and cached source reconstruction and rejected all 28 malformed
lock candidates before staging source, including coordinated snapshot changes
and invalid cached provenance.

- Official Debian ARM64 image:
  `docker.io/library/debian@sha256:da496358bd6934d2bd6a563a33176a2e50eff5490c54b4ac6fb051b69fef4071`.
  Raw child-manifest SHA256 equals that digest; official index SHA256 is
  `a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a`.
- Fixed snapshot: `20261006T000000Z`, now historical at resolution.
  Source changelog epoch: `1754902287`.
- Toolchain: GCC `14.2.0`, Meson `1.7.0`, dpkg `1.22.22`.
  The lock records all 385 installed dependency versions, architectures and
  package hashes from authenticated Packages bytes.
- Archive keyring: Debian package `debian-archive-keyring=2025.1`;
  keyring file SHA256
  `506b815cbb32d9b6066b4a2aa524071e071761e7e7f68c3ac74f3061ba852017`.
  Maintainer keyring: `debian-keyring=2025.07.26`; file SHA256
  `052303f4083e56def3c82a94b16954e41bbd96b81624fc5a275791d2540bef2d`.
- Initial signed certificate closure includes `ca-certificates=20250419`,
  package SHA256
  `ef590f89563aa4b46c8260d49d1cea0fc1b181d19e8df3782694706adf05c184`.

Verified archive signer set:

```text
41587F7DB8C774BCCF131416762F67A0B2C39DE4
4CB50190207B4758A3F73A796ED0E7B82643E131
B8E5F13176D2A7A75220028078DBA3BC47EF2265
```

Descriptor signer: `796DB393DC3FF40222B6EA22D3EBB5966BB99196`.
The scalar archive pin is the first verified fingerprint above. Actual dated
request paths, final content-addressed HTTPS URIs and metadata/source hashes
are retained in the lock and signature report; no URI mapping was inferred.

| Verified source file | SHA256 |
| --- | --- |
| `modemmanager_1.24.0-1+deb13u1.dsc` | `40fad1bfeb286fcbeaf449286585f765e96b01c4e53dd3a80108e627624237e2` |
| `modemmanager_1.24.0.orig.tar.xz` | `63ded4c0f3936bb0db5ae35ef1dfd57c5d5b4dd8a5cdaa7fb2182255218c9168` |
| `modemmanager_1.24.0-1+deb13u1.debian.tar.xz` | `0362e74213576b3f830b344f139407843a6caf6b9ae892c5a085a340da6999f2` |

Input-evidence artifact ID `11383061442`, ZIP SHA256
`513fe16b8bdde18d63036467f242f99f98b9287f7be28673e1d23af634f50f71`.
Signature-report SHA256:
`871d91b10c7a12e35cc854bd33e07eedc748e321223adea58d1fa4984c254cb7`.
This establishes source/build-input provenance. Provider patching, package
builds, reproducibility and modem/audio qualification are later tasks.

## Candidate package evidence (qualification pending)

The producer software milestone is closed at `bb189f172516a95b9203cd8d4f5bbf853e2ee01c`:
13 generic, 35 SIMTech and 32 upstream native cases passed. The tracked candidate
profile describes the observed SIM7600G-H identity and candidate dictionary only;
`qualification_pending` and empty evidence do not establish firmware framing,
reset qualification, consumer eligibility, installation or successful calls.

Packaging uses the same signed source and exact installed dependency lock. The
source package preserves authenticated Debian 0001 followed by unchanged local
0002–0004. The tracked local series stays local-only. `build/build.sh` records the
exact Debian rules/changelog overlay as `debian-packaging.diff`, also inside
`debian/yoyopod-inputs/`; it is not a quilt patch against already changed Debian
metadata. Hardening remains `+all`, AT over D-Bus is disabled, and builtin plugins
match the native-tested link configuration. Normal service, polkit and D-Bus
configuration are preserved. All upstream/focused tests execute in the actual
Debian build; private test buses and the built daemon/GIR/typelib are used.

Fixed interfaces, executed inside a fresh locked native ARM container:

```sh
bash build/build.sh --lock source-lock.json --repo-sha FULL_SHA --ci-run-id RUN --out /evidence/output
bash build/compare.sh FIRST SECOND
```

The build path is always `/build/modemmanager-1.24.0`. SOURCE_DATE_EPOCH comes from
the source lock. Repository/run identity and profile do not enter package bytes.
The recipe, overlays, canonical tests, complete patch series, original archives,
`.dsc`, corresponding dependency sources and copyright notices are retained and
hashed. The daemon hash comes from the actual extracted runtime package executable.
The strict schema, jq checks and Python standard-library validator reject unknown
fields, duplicate JSON keys, tampered files, traversal, symlinks and unlisted files.

The runtime closure starts from produced `modemmanager` and `libmm-glib0` control
records (`dpkg-deb -f`), follows Depends/Pre-Depends including alternatives/Provides,
and includes only selected locked ARM64/all packages from authenticated Packages.
It does not ship the unrelated build tool closure. Exact source packages are
resolved from authenticated Sources records, hash/size checked and accompanied by
binary copyright notices. An unavailable dependency/source fails closed with
NEEDS_CONTEXT; the recipe never changes the lock or installs missing tools.

`provider_packages=true` is an optional interim native CI evidence mode. Two fresh
containers build at identical internal paths. The second sees the first output
read-only solely for comparison after its build. Both complete manifests and all
package/corresponding-source bytes must match. Run-specific buildinfo/changes/log
comparisons remain factual and are reported separately; differences there are
not claimed reproducible. Failed or ambiguous builds upload diagnostic logs,
manifests and hashes only, never candidate `.deb` or source payloads. Success
uploads matching evidence for the exact checkout SHA. This is not a deployment
selector; Task 6 must integrate into the single nine-binary Rust artifact.

Local checks: `python3 tests/test-packaging.py` and `bash -n` for the fixed shell
entrypoints. The symlink case must run without skipping on native Linux. Native
package/reproducibility results, scoped review, artifact integration, consumer
and installer gates remain required. Do not install or initiate calls from this
packaging evidence. Task 8's framing-feasibility/maintenance gate still applies.
