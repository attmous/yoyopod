#!/usr/bin/env bash
# Exercise the real transaction orchestration with harmless effects only.
set -euo pipefail
provider_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
transaction="$provider_root/deploy/transaction.sh"
[[ -f "$transaction" ]] || { echo 'missing real provider transaction' >&2; exit 1; }
source "$transaction"
declare -F provider_main >/dev/null
declare -F write_recovery_record >/dev/null

stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
trace="$stage/trace"
: > "$trace"
record() { printf '%s\n' "$1" >> "$trace"; }

# No stage/receipt schema is fabricated here. A rejected real verify_stage
# effect must return before call/lane checks, prior capture or any service stop.
verify_stage() { record verify-stage; return 1; }
require_dev_no_calls() { record require-dev-no-calls; }
capture_prior() { record capture-prior; }
stop_native() { record stop-native; }
stop_provider() { record stop-provider; }
install_candidate() { record install-candidate; }
start_provider() { record start-provider; }
verify_provider_init() { record verify-provider-init; }
start_native() { record start-native; }
verify_native_expected() { record verify-native-expected; }
restore_prior_packages() { record restore-prior-packages; }
restore_prior_service() { record restore-prior-service; }
restore_prior_rust() { record restore-prior-rust; }

if provider_main "$stage" yoyopod-dev.service yoyopod-prod.service; then
  echo 'accepted failed provider staging' >&2; exit 1
fi
[[ $(cat "$trace") == verify-stage ]] || {
  echo 'provider staging failure reached a later effect' >&2
  cat "$trace" >&2
  exit 1
}
echo 'PASS real provider orchestration rejects staging before any stop'
