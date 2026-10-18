#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 ]] || { echo "usage: $0 PROVIDER_DIR" >&2; exit 2; }

provider_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
repo_root=$(git -C "$provider_root" rev-parse --show-toplevel)
repo_sha=$(git -C "$repo_root" rev-parse HEAD)
bundler="$provider_root/build/bundle.sh"
bash "$provider_root/build/validate-manifest.sh" "$1"
[[ -f "$bundler" ]] || { echo 'missing real provider/Rust bundler' >&2; exit 1; }
# Sourcing the production verifier must only define functions. The same verifier
# is used by production before publication and by later archive mutation cases.
source "$bundler"
declare -F bundle_verify >/dev/null

fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT
cp -a -- "$1" "$fixture/provider"
provider_sha=$(jq -er .repo_sha "$fixture/provider/manifest.json")
ci_run_id=$(jq -er .ci_run_id "$fixture/provider/manifest.json")

# These are labelled dummy Rust outputs, never production ARM binaries.
for entry in cloud:yoyopod-cloud-host media:yoyopod-media-host \
  network:yoyopod-network-host onpi:yoyopod-on-pi power:yoyopod-power-host \
  runtime:yoyopod-runtime speech:yoyopod-speech-host ui:yoyopod-ui-host \
  voip:yoyopod-voip-host; do
  directory=${entry%%:*}; binary=${entry#*:}
  mkdir -p -- "$fixture/rust/device/$directory/build"
  printf 'synthetic test binary %s\n' "$binary" > "$fixture/rust/device/$directory/build/$binary"
  chmod 0755 "$fixture/rust/device/$directory/build/$binary"
done

reject_bundle() {
  local name=$1 expected_sha=$2 expected_run=$3
  local out="$fixture/$name.tar.gz"
  if bash "$bundler" --repo-sha "$expected_sha" --ci-run-id "$expected_run" \
    --provider "$fixture/provider" --rust-root "$fixture/rust" --out "$out"; then
    echo "accepted $name" >&2; exit 1
  fi
  [[ ! -e "$out" ]] || { echo "published rejected $name" >&2; exit 1; }
}

if [[ "$provider_sha" != "$repo_sha" ]]; then
  # A genuine older candidate is useful rejection evidence. Its provenance is
  # never rewritten to manufacture a current-checkout positive fixture.
  reject_bundle provider-from-another-checkout "$repo_sha" "$ci_run_id"
  echo 'PASS prior-provider/current-checkout rejection; current ARM provider required for positive/mutation cases'
  exit 0
fi

out="$fixture/bundle.tar.gz"
bash "$bundler" --repo-sha "$repo_sha" --ci-run-id "$ci_run_id" \
  --provider "$fixture/provider" --rust-root "$fixture/rust" --out "$out"
bundle_verify "$out" "$repo_sha" "$ci_run_id"

# Independent assertions inspect the actual archive and bytes. Rejection of
# malformed archives belongs to the production verifier, not this test oracle.
python3 -I - "$out" "$fixture/rust" "$fixture/provider" "$repo_sha" "$ci_run_id" <<'PY'
import hashlib
import json
import pathlib
import sys
import tarfile

archive, rust, provider, sha, run = sys.argv[1:]
rust, provider = pathlib.Path(rust), pathlib.Path(provider)
paths = [
    "device/cloud/build/yoyopod-cloud-host",
    "device/media/build/yoyopod-media-host",
    "device/network/build/yoyopod-network-host",
    "device/onpi/build/yoyopod-on-pi",
    "device/power/build/yoyopod-power-host",
    "device/runtime/build/yoyopod-runtime",
    "device/speech/build/yoyopod-speech-host",
    "device/ui/build/yoyopod-ui-host",
    "device/voip/build/yoyopod-voip-host",
]
digest = lambda data: hashlib.sha256(data).hexdigest()
with tarfile.open(archive, "r:gz") as tar:
    members = {member.name: member for member in tar.getmembers() if member.isfile()}
    read = lambda name: tar.extractfile(members[name]).read()
    root = json.loads(read("manifest.json"))
    assert set(root) == {"schema_version", "repo_sha", "ci_run_id", "binaries", "provider_manifest_sha256"}
    assert type(root["schema_version"]) is int and root["schema_version"] == 1
    assert (root["repo_sha"], root["ci_run_id"]) == (sha, run)
    assert root["binaries"] == [{"file": name, "sha256": digest((rust / name).read_bytes())} for name in paths]
    for name in paths:
        assert read(name) == (rust / name).read_bytes(), name
    inner_bytes = (provider / "manifest.json").read_bytes()
    assert read("providers/modemmanager/manifest.json") == inner_bytes
    assert root["provider_manifest_sha256"] == digest(inner_bytes)
    inner = json.loads(inner_bytes)
    provider_files = {"manifest.json", "profile.json"}
    for section in ("packages", "source_files", "reports"):
        provider_files.update(row["file"] for row in inner[section])
    for name in provider_files:
        assert read("providers/modemmanager/" + name) == (provider / name).read_bytes(), name
    expected = {"manifest.json", *paths, *("providers/modemmanager/" + name for name in provider_files)}
    assert set(members) == expected
PY

wrong_sha=0000000000000000000000000000000000000000
[[ "$repo_sha" != "$wrong_sha" ]] || wrong_sha=1111111111111111111111111111111111111111
if bash "$bundler" --repo-sha "$wrong_sha" --ci-run-id "$ci_run_id" \
  --provider "$fixture/missing-input" --rust-root "$fixture/missing-rust" \
  --out "$fixture/checkout-mismatch.tar.gz" > "$fixture/checkout-mismatch.log" 2>&1; then
  echo 'accepted checkout/SHA mismatch' >&2; exit 1
fi
grep -Fxq 'checkout/SHA mismatch' "$fixture/checkout-mismatch.log"
[[ ! -e "$fixture/checkout-mismatch.tar.gz" ]]
reject_bundle wrong-provider-sha "$wrong_sha" "$ci_run_id"
reject_bundle wrong-provider-run "$repo_sha" "${ci_run_id}0"

# Mutate real input copies, keeping the original candidate and provenance intact.
license=$(jq -er '[.source_files[].file | select(startswith("source/licenses/"))][0]' "$fixture/provider/manifest.json")
mv -- "$fixture/provider/$license" "$fixture/license.original"
reject_bundle missing-provider-license "$repo_sha" "$ci_run_id"
ln -s -- "$fixture/license.original" "$fixture/provider/$license"
reject_bundle symlink-provider-license "$repo_sha" "$ci_run_id"
rm -- "$fixture/provider/$license"
mv -- "$fixture/license.original" "$fixture/provider/$license"
rust_binary="$fixture/rust/device/runtime/build/yoyopod-runtime"
mv -- "$rust_binary" "$fixture/rust.original"
ln -s -- "$fixture/rust.original" "$rust_binary"
reject_bundle symlink-rust-binary "$repo_sha" "$ci_run_id"
rm -- "$rust_binary"
mv -- "$fixture/rust.original" "$rust_binary"

# All malformed archives go through the very verifier used before publication.
# A byte-identical rewrite first proves this mutation writer produces valid tar.
python3 -I - "$bundler" "$out" "$fixture" "$repo_sha" "$ci_run_id" <<'PY'
import copy
import gzip
import hashlib
import json
import pathlib
import subprocess
import sys
import tarfile

bundler, archive, temporary, sha, run = sys.argv[1:]
temporary = pathlib.Path(temporary)
with tarfile.open(archive, "r:gz") as tar:
    original = [(copy.copy(member), tar.extractfile(member).read() if member.isfile() else None)
                for member in tar.getmembers()]


def verify(name, rows, accepted=False, required_error=None, prefix_split=False):
    path = temporary / (name + ".tar.gz")
    with gzip.open(path, "wb") as tar:
        for member, data in rows:
            member = copy.copy(member)
            if data is not None:
                member.size = len(data)
            info = member.get_info()
            if prefix_split and member.name == "device/runtime/build/yoyopod-runtime":
                info["prefix"], info["name"] = member.name.rsplit("/", 1)
            tar.write(member.create_ustar_header(info, "utf-8", "strict"))
            if data is not None:
                tar.write(tarfile.TarInfo._create_payload(data))
        tar.write(b"\0" * (2 * tarfile.BLOCKSIZE))
    result = subprocess.run(["bash", "-c", 'source "$1"; bundle_verify "$2" "$3" "$4"',
                             "bundle-test", bundler, str(path), sha, run], capture_output=True, text=True)
    assert (result.returncode == 0) == accepted, (name, result.returncode, result.stderr)
    if required_error is not None:
        assert required_error in result.stderr, (name, result.stderr)
    print("PASS " + ("accepted " if accepted else "rejected ") + name)
    path.unlink()


def replace(name, data):
    return [(copy.copy(member), data if member.name == name else old) for member, old in original]


def root_change(name, change):
    root = json.loads(next(data for member, data in original if member.name == "manifest.json"))
    change(root)
    verify(name, replace("manifest.json", json.dumps(root).encode()))


def inner_change(name, field, value):
    inner_path = "providers/modemmanager/manifest.json"
    inner = json.loads(next(data for member, data in original if member.name == inner_path))
    inner[field] = value
    encoded = json.dumps(inner).encode()
    root = json.loads(next(data for member, data in original if member.name == "manifest.json"))
    root["provider_manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    rows = replace(inner_path, encoded)
    rows = [(member, json.dumps(root).encode() if member.name == "manifest.json" else data)
            for member, data in rows]
    verify(name, rows)


verify("valid-rewritten-archive", original, accepted=True)
verify("valid-USTAR-prefix-split", original, accepted=True, prefix_split=True)
binary = "device/runtime/build/yoyopod-runtime"
for name, raw_name, kind in (
    ("raw-double-directory-slash", "device//", tarfile.DIRTYPE),
    ("raw-triple-directory-slash", "device///", tarfile.DIRTYPE),
    ("raw-regular-as-directory", "device/", tarfile.AREGTYPE),
):
    rows = []
    for member, data in original:
        member = copy.copy(member)
        if member.name == "device":
            member.name, member.type = raw_name, kind
        rows.append((member, data))
    verify(name, rows, required_error="noncanonical archive path")
for name, kind, data in (
    ("hidden-GNU-longname", tarfile.GNUTYPE_LONGNAME, binary.encode() + b"\0"),
    ("hidden-GNU-longlink", tarfile.GNUTYPE_LONGLINK, binary.encode() + b"\0"),
    ("hidden-PAX-local", tarfile.XHDTYPE, b""),
    ("hidden-PAX-global", tarfile.XGLTYPE, b""),
):
    pseudo = tarfile.TarInfo("header")
    pseudo.type = kind
    rows = []
    for member, old in original:
        if member.name == binary:
            rows.append((pseudo, data))
        rows.append((member, old))
    verify(name, rows, required_error="unsupported raw USTAR type")
verify("rust-bytes-changed-after-manifest", replace(binary, b"changed real binary bytes\n"))
for name, prefix in (("missing-license", "providers/modemmanager/source/licenses/"),
                     ("missing-source", "providers/modemmanager/source/dependencies/")):
    removed = next(member.name for member, data in original if data is not None and member.name.startswith(prefix))
    verify(name, [(member, data) for member, data in original if member.name != removed])
inner_change("daemon-does-not-match-package", "daemon_sha256", "0" * 64)
inner_change("inner-SHA-mismatch", "repo_sha", "0" * 40)
inner_change("inner-run-mismatch", "ci_run_id", run + "0")
root_change("root-SHA-mismatch", lambda root: root.update(repo_sha="0" * 40))
root_change("root-run-mismatch", lambda root: root.update(ci_run_id=run + "0"))
root_change("unknown-root-field", lambda root: root.update(extra=True))
root_change("boolean-schema", lambda root: root.update(schema_version=True))
root_change("wrong-binary-order", lambda root: root["binaries"].reverse())
root_change("duplicate-binary", lambda root: root["binaries"].__setitem__(1, root["binaries"][0]))
root_bytes = next(data for member, data in original if member.name == "manifest.json")
verify("duplicate-root-key", replace("manifest.json", root_bytes.rstrip()[:-1] + b',"schema_version":1}'))
duplicate = next((member, data) for member, data in original if member.name == binary)
verify("duplicate-archive-member", original + [duplicate])
for name, path, kind in (
    ("traversal", "../outside", tarfile.REGTYPE),
    ("alias-path", "device/./extra", tarfile.REGTYPE),
    ("absolute-path", "/outside", tarfile.REGTYPE),
    ("extra-file", "extra.txt", tarfile.REGTYPE),
    ("extra-directory", "unexpected", tarfile.DIRTYPE),
    ("symlink", "device/extra", tarfile.SYMTYPE),
    ("hardlink", "device/extra", tarfile.LNKTYPE),
    ("fifo", "device/extra", tarfile.FIFOTYPE),
):
    member = tarfile.TarInfo(path)
    member.type = kind
    member.linkname = binary if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
    verify(name, original + [(member, b"extra" if kind == tarfile.REGTYPE else None)])
PY
echo 'PASS current provider actual bundle and mutation suite (dummy Rust outputs)'
