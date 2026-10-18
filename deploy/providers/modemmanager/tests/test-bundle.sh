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
reject_bundle wrong-provider-sha "$wrong_sha" "$ci_run_id"
reject_bundle wrong-provider-run "$repo_sha" "${ci_run_id}0"
echo 'PASS actual bundle bytes, strict root fields, provider membership and SHA/run rejection'
