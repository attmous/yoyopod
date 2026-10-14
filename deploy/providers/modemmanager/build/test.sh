#!/usr/bin/env bash
set -euo pipefail
case "$*" in
    '--filter test-voice-audio') mode=focused; focused_test=test-voice-audio ;;
    '--filter test-simtech-audio') mode=simtech; focused_test=test-simtech-audio ;;
    '--upstream') mode=upstream ;;
    *) echo 'usage: build/test.sh --filter test-voice-audio | --filter test-simtech-audio | --upstream' >&2; exit 2 ;;
esac
root=$(cd "$(dirname "$0")/.." && pwd)
work=/evidence/tests
mkdir -p "$work"
# The tracked lock alone authenticates the full environment, source and patch bytes.
bash "$root/build/verify-inputs.sh" "$root/source-lock.json" "$work/inputs"
source_dir="$work/inputs/source"
# Refuse a series which differs from the ordered, verified patch pins.
jq -r '.patches[].path | sub("^patches/"; "")' "$root/source-lock.json" > "$work/locked-series"
cmp "$root/patches/series" "$work/locked-series"
while IFS= read -r patch_name; do
    patch --batch --fuzz=0 -d "$source_dir" -p1 < "$root/patches/$patch_name"
done < "$work/locked-series"
# The recorded test patch is the build input; canonical sources must match it.
for test_source in provider-fixture.h provider-fixture.c test-voice-audio.c test-simtech-audio.c; do
    cmp "$root/tests/$test_source" "$source_dir/src/tests/$test_source"
done
build_dir="$work/build-$mode"
# A repeat may not reuse binaries built from previous source/fixture bytes.
test ! -e "$build_dir"
meson setup "$build_dir" "$source_dir" -Dtests=true -Dbuiltin_plugins=true -Dgtk_doc=false -Dat_command_via_dbus=false
if [[ "$mode" != upstream ]]; then
    meson test -C "$build_dir" --print-errorlogs "$focused_test"
else
    # Upstream private-bus activation needs the daemon and GIR/typelib outputs,
    # which are not dependencies of the test executables themselves.
    meson compile -C "$build_dir"
    GI_TYPELIB_PATH="$build_dir/libmm-glib" \
    LD_LIBRARY_PATH="$build_dir/libmm-glib" \
        meson test -C "$build_dir" --print-errorlogs --no-suite yoyopod-provider
fi
