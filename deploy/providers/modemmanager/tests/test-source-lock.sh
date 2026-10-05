#!/usr/bin/env bash
# Catch missing schema/provenance checks and acceptance of changed signed bytes.
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
# Focused signature regression can execute without ARM/package tooling. Inputs
# must be genuine signed Debian metadata and its trusted archive keyring.
if [[ ${1:-} == --archive-signature ]]; then
    [[ $# == 4 ]] || { echo 'usage: test-source-lock.sh --archive-signature KEYRING INRELEASE EXPECTED_SIGNER' >&2; exit 1; }
    source build/verify-inputs.sh
    selected=$(signer "$2" "$3" "$test_dir/archive-status" archive)
    [[ "$selected" == "$4" ]] || { echo 'FAIL: deterministic archive signer mismatch' >&2; exit 1; }
    [[ $(wc -l < "$test_dir/archive-status.fingerprints") -gt 1 ]] || { echo 'FAIL: fixture does not exercise multiple verified signatures' >&2; exit 1; }
    echo "PASS: genuine multi-signature archive selected $selected"
    cat "$test_dir/archive-status.fingerprints"
    # The same helper remains strict for descriptors: a genuine multi-signer
    # document cannot pass the distinct descriptor policy.
    if signer "$2" "$3" "$test_dir/descriptor-status" descriptor; then
        echo 'FAIL: descriptor accepted multiple signers' >&2; exit 1
    fi
    echo 'PASS: descriptor policy rejects multiple signers'
    exit 0
fi
# This exercises the exact network/cache helper used by the validator with
# independently signature-verified real metadata, without an invented lock.
if [[ ${1:-} == --request-provenance ]]; then
    [[ $# == 5 ]] || { echo 'usage: test-source-lock.sh --request-provenance KEYRING INRELEASE REQUEST_URI FINAL_URI' >&2; exit 1; }
    source build/verify-inputs.sh
    signer "$2" "$3" "$test_dir/archive-status" archive >/dev/null
    expected=$(hash "$3")
    fetch "$4" "$test_dir/metadata" "$expected" "$5"
    if fetch "$4" "$test_dir/false-final" "$expected" 'https://snapshot.debian.org/file/0000000000000000000000000000000000000000/InRelease'; then
        echo 'FAIL: accepted false request-to-final mapping' >&2; exit 1
    fi
    echo 'PASS: rejected false request-to-final mapping'
    # A locally editable URI sidecar cannot authorize a cached response.
    printf 'https://snapshot.debian.org/file/0000000000000000000000000000000000000000/InRelease' > "$test_dir/metadata.uri"
    fetch "$4" "$test_dir/metadata" "$expected" "$5"
    [[ $(cat "$test_dir/metadata.uri") == "$5" ]] || { echo 'FAIL: trusted editable cached URI sidecar' >&2; exit 1; }
    echo 'PASS: genuine dated redirect rechecked on cache hit'
    if fetch "${4%InRelease}never-requested-InRelease" "$test_dir/metadata" "$expected" "$5"; then
        echo 'FAIL: accepted nonexistent dated request using cached bytes' >&2; exit 1
    fi
    echo 'PASS: rejected changed dated request despite cached bytes'
    substituted=$(printf '%s' "$4" | sed -E 's|/archive/debian/[0-9]{8}T[0-9]{6}Z/|/archive/debian/20000101T000000Z/|')
    if fetch "$substituted" "$test_dir/metadata" "$expected" "$5"; then
        echo 'FAIL: accepted substituted snapshot using cached bytes' >&2; exit 1
    fi
    echo 'PASS: rejected substituted dated snapshot despite cached bytes'
    exit 0
fi
valid_lock="$test_dir/resolved.json"
if [[ $# == 1 ]]; then
    cp -- "$1" "$valid_lock"
else
    bash build/resolve-lock.sh "$valid_lock"
fi
bash build/verify-inputs.sh "$valid_lock" "$test_dir/valid"
test -f "$test_dir/valid/source/debian/control"
test -f "$test_dir/valid/signature-report.json"
bash build/verify-inputs.sh "$valid_lock" "$test_dir/valid"
echo 'PASS: positive cached-input reconstruction'

reject() {
    local name=$1 mutation=$2 cached=${3:-fresh}
    jq "$mutation" "$valid_lock" > "$test_dir/$name.json"
    if [[ "$cached" == cached ]]; then
        mkdir "$test_dir/$name-cache"
        cp -a "$test_dir/valid/metadata" "$test_dir/valid/downloads" "$test_dir/$name-cache/"
    fi
    if bash build/verify-inputs.sh "$test_dir/$name.json" "$test_dir/$name-cache" > "$test_dir/$name.log" 2>&1; then
        cat "$test_dir/$name.log" >&2
        echo "FAIL: accepted $name" >&2
        exit 1
    fi
    if [[ -d "$test_dir/$name-cache/source" ]]; then
        echo "FAIL: extracted source before rejecting $name" >&2
        exit 1
    fi
    echo "PASS: rejected $name"
    cat "$test_dir/$name.log"
}
reject missing-image 'del(.image)'
reject bad-hash '.sources[0].sha256 = "00"'
reject changed-source-hash '.sources[0].sha256 = ("0" * 64)'
reject descriptor-signer '(.signed_metadata[] | select(.kind == "dsc").signer_fingerprint) = ("0" * 40)'
reject metadata-hash '(.signed_metadata[] | select(.kind == "packages").sha256) = ("0" * 64)'
reject dependency-version '.build_dependencies[0].version = "0:0-invalid"'
reject dependency-hash '.build_dependencies[0].sha256 = ("0" * 64)'
reject wrong-architecture '.architecture = "amd64"'
reject floating-snapshot '.snapshot = "latest"'
reject changed-snapshot '.snapshot = "20000101T000000Z"'
reject altered-release-request '(.signed_metadata[]|select(.kind=="release").request_uri) |= sub("/InRelease$"; "/never-requested-InRelease")'
reject altered-packages-request '(.signed_metadata[]|select(.kind=="packages").request_uri) |= sub("/Packages[.]xz$"; "/Sources.xz")'
reject altered-sources-request '(.signed_metadata[]|select(.kind=="sources").request_uri) |= sub("/Sources[.]xz$"; "/Packages.xz")'
reject descriptor-request '(.signed_metadata[]|select(.kind=="dsc").request_uri) = (.sources[]|select(.name|endswith(".orig.tar.xz"))|.request_uri)'
reject coordinated-snapshot '.snapshot = "20000101T000000Z" | (.signed_metadata[].request_uri,.sources[].request_uri) |= sub("/archive/debian/[0-9]{8}T[0-9]{6}Z/"; "/archive/debian/20000101T000000Z/")'
reject cached-altered-release-request '(.signed_metadata[]|select(.kind=="release").request_uri) |= sub("/InRelease$"; "/never-requested-InRelease")' cached
reject cached-coordinated-snapshot '.snapshot = "20000101T000000Z" | (.signed_metadata[].request_uri,.sources[].request_uri) |= sub("/archive/debian/[0-9]{8}T[0-9]{6}Z/"; "/archive/debian/20000101T000000Z/")' cached
reject wrong-request-origin '.signed_metadata[0].request_uri = "https://example.invalid/InRelease"'
reject wrong-final-origin '.signed_metadata[0].uri = "https://example.invalid/InRelease"'
reject unknown-root '.unknown = true'
reject unknown-dependency '.build_dependencies[0].unknown = true'
reject empty-dependencies '.build_dependencies = []'
reject missing-tool-dependency '.build_dependencies |= map(select(.name != "meson"))'
reject unknown-metadata '.signed_metadata[0].unknown = true'
reject wrong-keyring '.maintainer_keyring_sha256 = ("0" * 64)'
reject wrong-source-date '.source_date_epoch = 1'
reject wrong-toolchain '.toolchain.gcc = "0.0.0"'
reject wrong-image '.image = "docker.io/library/debian@sha256:" + ("0" * 64)'
echo 'PASS: source lock validation suite'
