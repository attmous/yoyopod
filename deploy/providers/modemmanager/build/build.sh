#!/usr/bin/env bash
# Fixed native ARM packaging entrypoint. No install or hardware operations.
set -euo pipefail
umask 022
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ $# == 8 && $1 == --lock && $3 == --repo-sha && $5 == --ci-run-id && $7 == --out ]] || {
    echo 'usage: build.sh --lock LOCK --repo-sha SHA --ci-run-id RUN --out DIR' >&2; exit 2;
}
lock=$(realpath -e -- "$2")
repo_sha=$4
ci_run_id=$6
out=$(realpath -m -- "$8")
[[ $repo_sha =~ ^[0-9a-f]{40}$ && $ci_run_id =~ ^[0-9]+$ ]] || exit 2
[[ $(uname -m) == aarch64 && $(dpkg --print-architecture) == arm64 ]] || exit 2
[[ ! -e /build && ! -e "$out" && "$out" == /evidence/* ]] || {
    echo 'fresh /build and output under /evidence required' >&2; exit 2;
}
[[ -z ${DEB_BUILD_OPTIONS:-} && -z ${DEB_BUILD_PROFILES:-} ]] || exit 2
export LC_ALL=C.UTF-8 TZ=UTC
SOURCE_DATE_EPOCH=$(jq -er .source_date_epoch "$lock")
export SOURCE_DATE_EPOCH
mkdir -p /build "$out/packages" "$out/source/dependencies" "$out/source/licenses" "$out/reports"
# This verifies the exact installed closure, image, signatures, source and patches.
bash "$root/build/verify-inputs.sh" "$lock" /build/inputs > "$out/reports/input-verification.log" 2>&1
cp /build/inputs/signature-report.json "$out/reports/"
mkdir -p "$out/source/provenance"
cp /build/inputs/metadata/release /build/inputs/metadata/packages /build/inputs/metadata/sources "$out/source/provenance/"
cp /build/inputs/metadata/*signature.txt* "$out/reports/"
source=/build/modemmanager-1.24.0
mv /build/inputs/source "$source"
cp /build/inputs/downloads/modemmanager_1.24.0.orig.tar.xz /build/
cp "$lock" "$out/source/source-lock.json"
cp "$root/profile.json" "$out/profile.json"
cp "$root/manifest.schema.json" "$out/source/manifest.schema.json"
cp -a "$root/patches" "$out/source/patches"
# Debian's 0001 is already applied by the authenticated dpkg-source extraction.
stock_patch=0001-shared-fibocom-don-t-assume-parent-implements-the-fi.patch
printf '%s\n' "$stock_patch" > /build/stock-series
cmp /build/stock-series "$source/debian/patches/series"
cp "$source/debian/patches/$stock_patch" "$out/source/patches/"
jq -r '.patches[].path | sub("^patches/"; "")' "$lock" > /build/local-series
cmp /build/local-series "$root/patches/series"
cat /build/stock-series /build/local-series > /build/final-series
while IFS= read -r patch_name; do
    cp "$root/patches/$patch_name" "$source/debian/patches/$patch_name"
done < /build/local-series
cp /build/final-series "$source/debian/patches/series"
cp /build/final-series "$out/source/patches/series"
(cd "$source" && dpkg-source --before-build .)
for file in provider-fixture.c provider-fixture.h test-voice-audio.c test-simtech-audio.c; do
    cmp "$root/tests/$file" "$source/src/tests/$file"
done
# BEGIN pre-build source reference
# dpkg-source --after-build unapplies quilt patches. Preserve these exact
# verified build inputs outside its working tree before dpkg-buildpackage.
reference_files=(src/mm-iface-modem-voice.c src/mm-iface-modem-voice.h src/mm-base-call.c src/mm-base-call.h src/mm-base-modem.c src/plugins/simtech/mm-shared-simtech.c src/meson.build src/tests/meson.build)
source_reference="$out/source/pre-build-reference"
mkdir -- "$source_reference"
for file in "${reference_files[@]}"; do
    mkdir -p -- "$(dirname -- "$source_reference/$file")"
    cp -- "$source/$file" "$source_reference/$file"
done
(cd "$source_reference" && sha256sum "${reference_files[@]}" > SHA256SUMS)
chmod -R a-w -- "$source_reference"
# END pre-build source reference
bash "$root/tests/test-source-reference.sh" > "$out/reports/source-reference-tests.log" 2>&1
# Record exact build-only overlays. Keep authenticated package/service/polkit files.
cp "$source/debian/rules" /build/original-rules
cp "$source/debian/changelog" /build/original-changelog
python3 - "$source/debian/rules" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
rules = path.read_text()
assert 'export DEB_BUILD_MAINT_OPTIONS = hardening=+all' in rules
assert rules.count('\t\t-Dvapi=true') == 1
rules = rules.replace('DEB_HOST_MULTIARCH ?=', 'DEB_HOST_GNU_TYPE ?= $(shell dpkg-architecture -qDEB_HOST_GNU_TYPE)\nDEB_HOST_MULTIARCH ?=')
rules = rules.replace('\t\t-Dvapi=true', '\t\t-Dvapi=true \\\n\t\t-Dat_command_via_dbus=false \\\n\t\t-Dbuiltin_plugins=true')
assert 'override_dh_auto_test:' not in rules
rules += '\n# Real daemon and typelib are built before dh_auto_test. Private test buses only.\n'
rules += 'override_dh_auto_test:\n'
rules += '\tGI_TYPELIB_PATH=$(CURDIR)/obj-$(DEB_HOST_GNU_TYPE)/libmm-glib LD_LIBRARY_PATH=$(CURDIR)/obj-$(DEB_HOST_GNU_TYPE)/libmm-glib dh_auto_test\n'
path.write_text(rules)
PY
version=$(jq -er .package_version "$lock")
changelog_date=$(date --utc --date="@$SOURCE_DATE_EPOCH" --rfc-email)
{
    printf 'modemmanager (%s) trixie; urgency=medium\n\n' "$version"
    printf '  * Record current SIMTech PCM selection and private voice audio lifecycle.\n\n'
    printf ' -- yoyopod contributors <noreply@yoyopod.invalid>  %s\n\n' "$changelog_date"
    cat "$source/debian/changelog"
} > /build/changelog
cp /build/changelog "$source/debian/changelog"
# Recipe and canonical tests accompany the source package. Repo/run/profile do
# not enter package bytes, allowing factual provenance and profile-only rebuilds.
mkdir -p "$source/debian/yoyopod-inputs/build" "$source/debian/yoyopod-inputs/tests"
cp "$lock" "$source/debian/yoyopod-inputs/source-lock.json"
# Explicit package-input set: later Task6 bundle/artifact scripts must never
# silently alter corresponding source under an already-published package version.
for file in build.sh compare.sh validate-manifest.sh package.py collect-evidence.py container-state.sh resolve-lock.sh verify-inputs.sh test.sh; do
    cp "$root/build/$file" "$source/debian/yoyopod-inputs/build/$file"
done
for file in provider-fixture.c provider-fixture.h test-voice-audio.c test-simtech-audio.c test-packaging.py test-diagnostic-collector.py test-container-state.sh test-source-reference.sh; do
    cp "$root/tests/$file" "$source/debian/yoyopod-inputs/tests/$file"
done
mkdir -p "$source/debian/yoyopod-inputs/tests/fixtures"
cp "$root/tests/fixtures/diagnostic-collector-review-1.sh" "$source/debian/yoyopod-inputs/tests/fixtures/diagnostic-collector-review-1.sh"
cp "$root/manifest.schema.json" "$source/debian/yoyopod-inputs/"
# Exact metadata overlay is evidence, not a quilt patch against debian/.
: > "$source/debian/yoyopod-inputs/debian-packaging.diff"
for file in rules changelog; do
    status=0
    diff -u --label "a/debian/$file" --label "b/debian/$file" "/build/original-$file" "$source/debian/$file" >> "$source/debian/yoyopod-inputs/debian-packaging.diff" || status=$?
    [[ "$status" == 1 ]] || exit 1
done
cp "$source/debian/yoyopod-inputs/debian-packaging.diff" "$out/source/debian-packaging.diff"
cp "$source/debian/rules" "$out/source/debian.rules"
cp "$source/debian/changelog" "$out/source/debian.changelog"
cp -a "$source/debian/yoyopod-inputs" "$out/source/build-inputs"
# Source date and common internal path are identical in the two fresh containers.
find "$source/debian" -exec touch --no-dereference --date="@$SOURCE_DATE_EPOCH" {} +
(cd "$source" && dpkg-checkbuilddeps && dpkg-buildpackage -us -uc) > "$out/reports/dpkg-buildpackage.log" 2>&1
# dh_auto_test is not skipped; retain the actual complete native Meson results.
build_dir="$source/obj-$(dpkg-architecture -qDEB_HOST_GNU_TYPE)"
cp "$build_dir/meson-logs/testlog"* "$out/reports/"
python3 - "$out/reports/testlog.json" <<'PY'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
assert len(rows) == 34, ('unexpected suite count', len(rows))
assert all(row['result'] == 'OK' for row in rows), 'failed/skipped native package tests'
for name, count in [('test-voice-audio', 13), ('test-simtech-audio', 35)]:
    tests = [row for row in rows if row['name'].endswith(name)]
    assert len(tests) == 1 and ('1..' + str(count)) in tests[0]['stdout']
PY
cp /build/*.dsc /build/*.tar.* "$out/source/"
cp /build/*.buildinfo /build/*.changes "$out/reports/"
# Keep authenticated baseline archives/descriptor as provenance and source closure.
mkdir -p "$out/source/baseline"
cp /build/inputs/downloads/modemmanager_1.24.0* "$out/source/baseline/"
# Reconstruct the emitted source and prove final series/patch/tests/overlays.
dpkg-source --no-check -x "/build/modemmanager_${version}.dsc" /build/reconstructed > "$out/reports/source-reconstruction.log" 2>&1
cmp /build/final-series /build/reconstructed/debian/patches/series
while IFS= read -r patch_name; do
    cmp "$out/source/patches/$patch_name" "/build/reconstructed/debian/patches/$patch_name"
done < /build/final-series
for file in provider-fixture.c provider-fixture.h test-voice-audio.c test-simtech-audio.c; do
    cmp "$root/tests/$file" "/build/reconstructed/src/tests/$file"
done
cmp "$out/source/debian.rules" /build/reconstructed/debian/rules
cmp "$out/source/debian.changelog" /build/reconstructed/debian/changelog
# BEGIN reconstructed source comparison
# Check the immutable pre-build bytes, not dpkg-source's unpatched work tree.
(cd "$source_reference" && sha256sum --check --strict SHA256SUMS)
for file in "${reference_files[@]}"; do
    cmp "$source_reference/$file" "/build/reconstructed/$file"
done
# END reconstructed source comparison
python3 "$root/build/package.py" closure "$lock" /build/inputs /build "$out"
# The daemon digest is measured from the produced runtime package executable.
mkdir /build/daemon
package=$(find "$out/packages" -maxdepth 1 -name 'modemmanager_*.deb' -print)
[[ $(printf '%s\n' "$package" | wc -l) == 1 ]] || exit 1
dpkg-deb -x "$package" /build/daemon
[[ -f /build/daemon/usr/sbin/ModemManager && ! -L /build/daemon/usr/sbin/ModemManager ]] || exit 1
daemon_sha=$(sha256sum /build/daemon/usr/sbin/ModemManager | cut -d ' ' -f 1)
python3 "$root/tests/test-packaging.py" > "$out/reports/packaging-tests.log" 2>&1
python3 "$root/build/package.py" manifest "$out" "$repo_sha" "$ci_run_id" "$daemon_sha"

bash "$root/build/validate-manifest.sh" "$out"
