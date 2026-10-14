#!/usr/bin/env bash
set -euo pipefail
case "$*" in
    '--filter test-voice-audio') mode=focused ;;
    '--upstream') mode=upstream ;;
    *) echo 'usage: build/test.sh --filter test-voice-audio | --upstream' >&2; exit 2 ;;
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
cp "$root/tests/provider-fixture.h" "$root/tests/provider-fixture.c" "$root/tests/test-voice-audio.c" "$source_dir/src/tests/"
build_dir="$work/build-$mode"
# A repeat may not reuse binaries built from previous source/fixture bytes.
test ! -e "$build_dir"
meson setup "$build_dir" "$source_dir" -Dtests=true -Dbuiltin_plugins=true -Dgtk_doc=false -Dat_command_via_dbus=false
if [[ "$mode" == focused ]]; then
    meson test -C "$build_dir" --print-errorlogs test-voice-audio
else
    meson test -C "$build_dir" --print-errorlogs --exclude-suite yoyopod-provider
fi
