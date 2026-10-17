#!/usr/bin/env bash
# Exercise the actual recipe comparison; tiny files are explicitly synthetic.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
recipe=${1:-"$root/build/build.sh"}
scratch=$(mktemp -d)
trap 'chmod -R u+w "$scratch" 2>/dev/null || true; rm -rf -- "$scratch"' EXIT
source="$scratch/work"
reconstructed="$scratch/reconstructed"
out="$scratch/output"
mkdir -p "$out/source"
files=(src/mm-iface-modem-voice.c src/mm-iface-modem-voice.h src/mm-base-call.c src/mm-base-call.h src/mm-base-modem.c src/plugins/simtech/mm-shared-simtech.c src/meson.build src/tests/meson.build)
for file in "${files[@]}"; do
    mkdir -p "$(dirname -- "$source/$file")" "$(dirname -- "$reconstructed/$file")"
    printf 'synthetic PATCHED input: %s\n' "$file" > "$source/$file"
    cp -- "$source/$file" "$reconstructed/$file"
done
# Run the real capture block if present. The baseline has none: its actual
# comparison below must then expose the post-build unapplication defect.
sed -n '/^# BEGIN pre-build source reference$/,/^# END pre-build source reference$/p' "$recipe" > "$scratch/capture.sh"
source "$scratch/capture.sh"
# Normal dpkg-source --after-build unapplication changes the working tree only.
for file in "${files[@]}"; do
    printf 'synthetic UNPATCHED stock input: %s\n' "$file" > "$source/$file"
done
if grep -q '^# BEGIN reconstructed source comparison$' "$recipe"; then
    declare -p reference_files > "$scratch/compare.sh"
    sed -n '/^# BEGIN reconstructed source comparison$/,/^# END reconstructed source comparison$/p' "$recipe" >> "$scratch/compare.sh"
else
    # Exact pre-fix loop, retained to support behavioral RED on a frozen recipe.
    sed -n '/^for file in src\/mm-iface-modem-voice.c /,/^done$/p' "$recipe" > "$scratch/compare.sh"
fi
[[ -s "$scratch/compare.sh" ]]
# Relocate only the fixed reconstruction directory into this harmless fixture.
sed 's@/build/reconstructed@${reconstructed}@g' "$scratch/compare.sh" > "$scratch/compare-relocated.sh"
export source reconstructed out
if [[ -n ${source_reference:-} ]]; then export source_reference; fi
bash -e "$scratch/compare-relocated.sh"
printf 'PASS patched reconstruction survives post-build unapplication\n'
printf 'TAMPERED reconstruction\n' >> "$reconstructed/src/mm-iface-modem-voice.c"
if bash -e "$scratch/compare-relocated.sh" > "$scratch/rejected.log" 2>&1; then
    echo 'accepted tampered reconstructed source' >&2
    exit 1
fi
printf 'PASS tampered reconstruction rejected by actual comparison\n'
