#!/usr/bin/env bash
# Fixed ownership/quiescence boundary; sourceable for controlled Docker effects.
CONTAINER_HELPER_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

container_docker() {
    # Attached package execution is bounded by the job; all control/readback
    # effects are independently bounded, including cleanup after interruption.
    if [[ "$1" == container && "$2" == start ]]; then
        docker "$@"
    else
        timeout --signal=TERM --kill-after=5s 25s docker "$@"
    fi
}
container_collect() { python3 "$CONTAINER_HELPER_DIR/collect-evidence.py" "$@"; }

container_begin() {
    local state=$1 name=$2
    [[ "$name" == first || "$name" == second ]] || return 1
    [[ -d "$state" && ! -L "$state" && ! -e "$state/$name.cid" ]] || return 1
    # Intent precedes launch: a missing/partial CID after interruption is ambiguous.
    (set -o noclobber; printf 'launch-intent\n' > "$state/$name.intent")
}

container_start() {
    local state=$1 name=$2 cid
    [[ "$name" == first || "$name" == second ]] || return 1
    [[ -d "$state" && ! -L "$state" && -f "$state/$name.intent" && ! -L "$state/$name.intent" &&
       -f "$state/$name.cid" && ! -L "$state/$name.cid" ]] || return 1
    cid=$(cat -- "$state/$name.cid")
    [[ "$cid" =~ ^[0-9a-f]{64}$ ]] || return 1
    (set -o noclobber; printf 'start-requested\n' > "$state/$name.start-intent") || return 1
    container_docker container start --attach "$cid"
}

container_present() {
    local cid=$1 ids id
    ids=$(container_docker container ls --all --no-trunc --format '{{.ID}}') || return 2
    while IFS= read -r id; do
        [[ -z "$id" || "$id" =~ ^[0-9a-f]{64}$ ]] || return 2
    done <<< "$ids"
    while IFS= read -r id; do
        [[ "$id" != "$cid" ]] || return 0
    done <<< "$ids"
    return 1
}

container_quiesce_one() {
    local state=$1 name=$2 cid present running exit_code
    [[ "$name" == first || "$name" == second ]] || return 1
    [[ -d "$state" && ! -L "$state" ]] || return 1
    if [[ ! -e "$state/$name.intent" && ! -e "$state/$name.cid" ]]; then
        printf 'never-launched\n' > "$state/$name.quiescence"
        return 0
    fi
    [[ -f "$state/$name.intent" && ! -L "$state/$name.intent" &&
       -f "$state/$name.cid" && ! -L "$state/$name.cid" ]] || return 1
    cid=$(cat -- "$state/$name.cid")
    [[ "$cid" =~ ^[0-9a-f]{64}$ ]] || return 1
    present=0
    container_present "$cid" || present=$?
    if [[ "$present" == 1 ]]; then
        printf 'confirmed-absent\n' > "$state/$name.quiescence"
        return 0
    fi
    [[ "$present" == 0 ]] || return 1
    if ! running=$(container_docker container inspect --format '{{.State.Running}} {{.State.Status}}' "$cid"); then
        # Best-effort bounded stop of only this recorded owned CID. An inspect
        # failure still blocks evidence reads, even if the stop happens to work.
        container_docker container stop --time 10 "$cid" >/dev/null 2>&1 || true
        return 1
    fi
    case "$running" in
      'true running') container_docker container stop --time 10 "$cid" >/dev/null || return 1 ;;
      'false exited'|'false created') ;;
      *) return 1 ;;
    esac
    if [[ "$running" != 'false created' ]]; then
        exit_code=$(container_docker container wait "$cid") || return 1
        [[ "$exit_code" =~ ^[0-9]+$ ]] || return 1
        running=$(container_docker container inspect --format '{{.State.Running}} {{.State.Status}}' "$cid") || return 1
        [[ "$running" == 'false exited' ]] || return 1
    fi
    container_docker container rm "$cid" >/dev/null || return 1
    present=0
    container_present "$cid" || present=$?
    [[ "$present" == 1 ]] || return 1
    printf 'stopped-waited-removed-confirmed-absent\n' > "$state/$name.quiescence"
}

container_quiesce_all() {
    local state=$1 failed=0 name
    [[ -d "$state" && ! -L "$state" ]] || return 1
    for name in first second; do
        container_quiesce_one "$state" "$name" || failed=1
    done
    [[ "$failed" == 0 ]]
}

container_collect_after_quiescence() {
    local state=$1 evidence=$2 destination=$3 mode=$4
    if container_quiesce_all "$state"; then
        container_collect "$evidence" "$destination" "$mode" || return 1
        printf '%s\n' '{"schema_version":1,"container_quiescence_proven":true,"proof":"owned_cids_confirmed_absent_or_never_launched"}' > "$destination/diagnostics/container-quiescence.json"
        if [[ -f "$state/quiescence-tests.log" && ! -L "$state/quiescence-tests.log" ]]; then
            cp -- "$state/quiescence-tests.log" "$destination/diagnostics/quiescence-tests.log"
        fi
    else
        # No source evidence is opened, hashed, tested or traversed here. This
        # fresh destination's parent is created by host mktemp outside mounts.
        (umask 077; mkdir -- "$destination" && mkdir -- "$destination/diagnostics") || return 1
        printf '%s\n' '{"schema_version":1,"accepted":false,"reason":"container_quiescence_unproven","untrusted_evidence_read":false}' > "$destination/diagnostics/collection.json"
        return 1
    fi
}
