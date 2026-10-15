#!/usr/bin/env bash
set -euo pipefail
[[ $# == 2 ]] || { echo 'usage: compare.sh FIRST SECOND' >&2; exit 2; }
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
first=$(realpath -e -- "$1")
second=$(realpath -e -- "$2")
[[ "$first" != "$second" ]] || { echo 'two independent outputs required' >&2; exit 2; }
# Outside either manifest tree: reports preserve actual run-specific differences.
report="${second}.comparison.json"
[[ ! -e "$report" ]] || { echo 'comparison report already exists' >&2; exit 2; }
bash "$root/build/validate-manifest.sh" "$first"
bash "$root/build/validate-manifest.sh" "$second"
python3 "$root/build/package.py" compare "$first" "$second" "$report"
cat -- "$report"
