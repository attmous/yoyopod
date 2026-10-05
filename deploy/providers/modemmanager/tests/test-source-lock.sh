#!/usr/bin/env bash
# Catch missing schema/provenance checks and acceptance of changed signed bytes.
set -euo pipefail
cd "$(dirname "$0")/.."
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
valid_lock="$test_dir/resolved.json"
if [[ $# == 1 ]]; then
    cp -- "$1" "$valid_lock"
else
    bash build/resolve-lock.sh "$valid_lock"
fi
bash build/verify-inputs.sh "$valid_lock" "$test_dir/valid"
test -f "$test_dir/valid/source/debian/control"
test -f "$test_dir/valid/signature-report.json"

reject() {
    local name=$1 mutation=$2
    jq "$mutation" "$valid_lock" > "$test_dir/$name.json"
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
