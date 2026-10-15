#!/usr/bin/env bash
# Test the actual orchestration, overriding only Docker and collection effects.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$root/build/container-state.sh"
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
cid=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
other=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
container_docker() {
    printf '%s\n' "$*" >> "$trace"
    [[ "$1" == container ]] || return 99
    case "$2" in
      start)
        [[ "$3" == --attach && "$4" == "$cid" && -s "$state/first.cid" ]] || return 99
        printf 'running\n' > "$physical"
        [[ "$scenario" != interrupted-client ]] || return 130
        ;;
      ls)
        [[ "$scenario" != failed-list ]] || return 1
        printf '%s\n' "$other"
        [[ $(cat "$physical") == absent ]] || printf '%s\n' "$cid"
        ;;
      inspect)
        [[ "${@: -1}" == "$cid" ]] || return 99
        [[ "$scenario" != failed-inspect ]] || return 1
        case $(cat "$physical") in
          running) printf 'true running\n' ;;
          created) printf 'false created\n' ;;
          *) printf 'false exited\n' ;;
        esac
        ;;
      stop)
        [[ "${@: -1}" == "$cid" ]] || return 99
        [[ "$scenario" != failed-stop ]] || return 1
        printf 'stopped\n' > "$physical"
        ;;
      wait)
        [[ "$3" == "$cid" && $(cat "$physical") == stopped ]] || return 99
        [[ "$scenario" != failed-wait ]] || return 1
        printf '143\n'
        ;;
      rm)
        [[ "$3" == "$cid" && $(cat "$physical") != running ]] || return 99
        [[ "$scenario" != failed-remove ]] || return 1
        printf 'absent\n' > "$physical"
        ;;
      *) return 99 ;;
    esac
}
container_collect() {
    printf 'COLLECT\n' >> "$trace"
    [[ $(cat "$physical") == absent ]] || return 99
    mkdir -p -- "$2/diagnostics"
    printf 'regular fixture\n' > "$2/diagnostics/fixture.log"
}
for scenario in running stopped created absent interrupted-client failed-stop failed-inspect failed-list failed-wait failed-remove ambiguous-launch invalid-cid; do
    state="$scratch/$scenario"
    mkdir -- "$state"
    trace="$state/trace"
    physical="$state/physical"
    : > "$trace"
    printf 'running\n' > "$physical"
    [[ "$scenario" != absent ]] || printf 'absent\n' > "$physical"
    [[ "$scenario" != stopped ]] || printf 'stopped\n' > "$physical"
    [[ "$scenario" != created ]] || printf 'created\n' > "$physical"
    container_begin "$state" first
    if [[ "$scenario" != ambiguous-launch ]]; then printf '%s\n' "$cid" > "$state/first.cid"; fi
    if [[ "$scenario" == invalid-cid ]]; then printf 'invalid\n' > "$state/first.cid"; fi
    if [[ "$scenario" == interrupted-client ]]; then
        start_status=0
        container_start "$state" first || start_status=$?
        [[ "$start_status" == 130 && $(cat "$physical") == running ]]
    fi
    if [[ "$scenario" == ambiguous-launch || "$scenario" == invalid-cid ]]; then
        if container_start "$state" first; then exit 1; fi
        ! grep -q 'container start' "$trace"
    fi
    status=0
    container_collect_after_quiescence "$state" "$state/UNTRUSTED-MISSING" "$state/upload" failure || status=$?
    case "$scenario" in
      running|stopped|created|absent|interrupted-client)
        [[ "$status" == 0 && $(cat "$physical") == absent ]]
        grep -qx COLLECT "$trace"
        ;;
      *)
        [[ "$status" != 0 ]]
        ! grep -qx COLLECT "$trace"
        grep -q '"untrusted_evidence_read":false' "$state/upload/diagnostics/collection.json"
        ;;
    esac
    # No mutation is issued against the unrelated container returned by ls.
    ! grep -E "(stop|wait|rm|inspect).*${other}" "$trace"
    printf 'PASS %s\n' "$scenario"
done

# Execute the ACTUAL source-input copy block with future Task6 files present.
original_root=$root
fixture_root="$scratch/recipe-input"
mkdir -p "$fixture_root/build" "$fixture_root/tests/fixtures"
for path in "$original_root/build/"*.sh "$original_root/build/"*.py; do cp "$path" "$fixture_root/build/"; done
for path in "$original_root/tests/"*.c "$original_root/tests/"*.h "$original_root/tests/"*.py "$original_root/tests/"*.sh; do cp "$path" "$fixture_root/tests/"; done
cp "$original_root/tests/fixtures/diagnostic-collector-review-1.sh" "$fixture_root/tests/fixtures/"
cp "$original_root/manifest.schema.json" "$fixture_root/"
printf 'future artifact script\n' > "$fixture_root/build/bundle.sh"
printf 'future artifact test\n' > "$fixture_root/tests/test-bundle.py"
sed -n '/^for file in build.sh /,/^# Exact metadata overlay/{ /^# Exact metadata overlay/d; p; }' "$original_root/build/build.sh" > "$scratch/copy-inputs.sh"
[[ -s "$scratch/copy-inputs.sh" ]]
(
    root=$fixture_root
    source="$scratch/recipe-result"
    mkdir -p "$source/debian/yoyopod-inputs/build" "$source/debian/yoyopod-inputs/tests"
    source "$scratch/copy-inputs.sh"
    [[ -f "$source/debian/yoyopod-inputs/build/container-state.sh" ]]
    [[ -f "$source/debian/yoyopod-inputs/tests/test-container-state.sh" ]]
    [[ ! -e "$source/debian/yoyopod-inputs/build/bundle.sh" ]]
    [[ ! -e "$source/debian/yoyopod-inputs/tests/test-bundle.py" ]]
)
printf 'PASS fixed-source-whitelist-excludes-future-artifact-inputs\n'
