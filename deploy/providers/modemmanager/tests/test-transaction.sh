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
(
  # Exercise the actual all-modem/owner cut, replacing only its read effects.
  mode=idle
  provider_owner() {
    if [[ "$mode" == replacement ]]; then
      local count
      count=$(cat "$stage/owner-count")
      printf '%s\n' "$((count+1))" > "$stage/owner-count"
      if [[ "$count" -gt 0 ]]; then printf ':1.11\n'; return; fi
    fi
    printf ':1.10\n'
  }
  provider_bus() {
    if [[ "$1" == call ]]; then
      printf '%s\n' '{"data":[{"/org/freedesktop/ModemManager1/Modem/0":{},"/org/freedesktop/ModemManager1/Modem/1":{}}]}'
    elif [[ "$5" == Calls ]]; then
      if [[ "$3" == */1 && ( "$mode" == secondary-call || "$mode" == state-error ) ]]; then
        printf '%s\n' '{"data":[["/org/freedesktop/ModemManager1/Call/9"]]}'
      else printf '%s\n' '{"data":[[]]}'; fi
    elif [[ "$5" == State ]]; then
      [[ "$mode" != state-error ]] || return 1
      printf '%s\n' '{"data":[3]}'
    else return 1; fi
  }
  for mode in idle secondary-call state-error replacement; do
    printf '0\n' > "$stage/owner-count"
    if provider_no_calls :1.10; then
      [[ "$mode" == idle ]] || { echo "accepted unsafe no-call proof $mode" >&2; exit 1; }
    else [[ "$mode" != idle ]] || { echo 'rejected same-owner actual idle proof' >&2; exit 1; }; fi
  done
)
echo 'PASS actual all-modem helper rejects secondary call/read error/new-owner empty list'
(
  # Exercise the actual pre-stop metadata check on real files. Only the account
  # lookup is synthetic for the deliberately unsupported UID; no root is needed.
  mkdir -- "$stage/restorable-config"
  printf prior > "$stage/restorable-config/settings"
  user=$(id -un)
  provider_config_restorable "$stage/restorable-config" "$user"
  different_uid=$(( $(id -u) + 1 ))
  id() {
    if [[ "$1" == -u && "${2:-}" == synthetic-other-owner ]]; then printf '%s\n' "$different_uid"
    elif [[ "$1" == -g && "${2:-}" == synthetic-other-owner ]]; then command id -g
    else command id "$@"; fi
  }
  ! provider_config_restorable "$stage/restorable-config" synthetic-other-owner
  chmod 4755 "$stage/restorable-config/settings"
  ! provider_config_restorable "$stage/restorable-config" "$user"
  chmod 0644 "$stage/restorable-config/settings"
  provider_config_restorable "$stage/restorable-config" "$user"
  mkdir -- "$stage/restorable-config/nested"
  for mode in 0500 0550 0600; do
    chmod "$mode" "$stage/restorable-config/nested"
    ! provider_config_restorable "$stage/restorable-config" "$user"
  done
  chmod 0750 "$stage/restorable-config/nested"
  provider_config_restorable "$stage/restorable-config" "$user"
)
echo 'PASS actual pre-stop config check rejects unsupported ownership/special mode and accepts ordinary metadata'
(
  # This harmless process remains classifiable after its executable is unlinked.
  cp -- /bin/sleep "$stage/yoyopod-runtime"
  "$stage/yoyopod-runtime" 30 & child=$!
  trap 'kill "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :' EXIT
  for attempt in $(seq 1 100); do
    [[ $(provider_process_executable "/proc/$child") != yoyopod-runtime ]] || break
    sleep 0.01
  done
  [[ $(provider_process_executable "/proc/$child") == yoyopod-runtime ]]
  rm -- "$stage/yoyopod-runtime"
  [[ $(provider_process_executable "/proc/$child") == yoyopod-runtime ]]
  systemctl() { case "$*" in *MainPID*) printf '0\n';; *ActiveState*) printf 'inactive\n';; stop*) :;; *) return 1;; esac; }
  # timeout's production flags are fixed; replace only the systemctl wait effect.
  timeout() { while [[ "$1" != systemctl ]]; do shift; done; "$@"; }
  ! stop_native yoyopod-dev.service
  kill "$child"; wait "$child" 2>/dev/null || :
  trap - EXIT
  stop_native yoyopod-dev.service
)
echo 'PASS actual deleted-executable child cannot escape the global native stop proof'
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

# Remaining cases call that same provider_main. Only its effects are replaced;
# provider_phase/provider_json_write/write_recovery_record remain production.
fixture_root=$stage
trap 'rm -rf -- "$fixture_root"' EXIT
old_identity='{"bus_id":"synthetic-bus","unique_owner":":1.10","pid":101,"process_start_ticks":1000,"running_daemon_sha256":"synthetic-old","installed_executable_sha256":"synthetic-old","package_version":"synthetic-old","architecture":"arm64"}'
new_identity='{"bus_id":"synthetic-bus","unique_owner":":1.11","pid":102,"process_start_ticks":1100,"running_daemon_sha256":"synthetic-new","installed_executable_sha256":"synthetic-new","package_version":"synthetic-new","architecture":"arm64"}'
fail_at=''; signal_at=''; rollback_fails=false; stop_fails=false; rollback_stop_fails=false; replace_after_stop=false
case_stage() {
  stage="$fixture_root/$1"
  mkdir -- "$stage"
  trace="$stage/trace"
  : > "$trace"
  printf '%s\n' "$old_identity" > "$stage/live-identity"
  for item in packages config rust; do printf old > "$stage/$item"; done
  fail_at=''; signal_at=''; rollback_fails=false; stop_fails=false; rollback_stop_fails=false; replace_after_stop=false
}
fault() {
  local name=$1
  if [[ "$signal_at" == "$name" ]]; then kill -TERM "$BASHPID"; return 1; fi
  if [[ "$fail_at" == "$name" && ! -e "$stage/fired-$name" ]]; then
    : > "$stage/fired-$name"
    return 1
  fi
}
effect() { record "$1"; fault "$1"; }
verify_stage() { effect verify-stage; }
require_dev_no_calls() { effect require-dev-no-calls || return; before_identity=$old_identity; before_modem=/org/freedesktop/ModemManager1/Modem/0; }
capture_prior() {
  effect capture-prior || return
  mkdir -- "$stage/prior" || return
  printf '%s\n' "$old_identity" > "$stage/prior/identity.json" || return
  prior_ready=true
}
provider_identity() { cat "$stage/live-identity"; }
provider_no_calls() { effect no-calls; }
provider_current_modem() { printf '%s\n' "$before_modem"; }
stop_native() {
  effect stop-native || return
  [[ "$stop_fails" != true && ( "$restoring" != true || "$rollback_stop_fails" != true ) ]] || return 1
  if [[ "$replace_after_stop" == true ]]; then printf '%s\n' "$new_identity" > "$stage/live-identity"; fi
}
stop_provider() { effect stop-provider || return; [[ "$stop_fails" != true && ( "$restoring" != true || "$rollback_stop_fails" != true ) ]]; }
install_candidate() {
  record install-candidate
  package_attempt_state=mutated
  printf partial > "$stage/packages"
  fault install-candidate || return
  for item in packages config rust; do printf new > "$stage/$item"; done
}
start_provider() { [[ "$provider_stopped" == false ]]; effect start-provider || return; printf '%s\n' "$new_identity" > "$stage/live-identity"; }
verify_provider_init() { effect verify-provider-init || return; current_identity=$new_identity; }
start_native() { [[ "$native_stopped" == false ]]; effect start-native; }
verify_native_expected() { effect verify-native-expected || return; outcome=installed_qualification_pending; }
restore_prior_packages() {
  effect restore-prior-packages || return
  [[ "$rollback_fails" != true ]] || return 1
  printf old > "$stage/packages"
}
restore_prior_service() { effect restore-prior-service || return; provider_start_provider || return; printf old > "$stage/config"; printf '%s\n' "$old_identity" > "$stage/live-identity"; started_identity=$old_identity; }
restore_prior_rust() { effect restore-prior-rust || return; printf old > "$stage/rust"; }
run_failure() {
  local expected=$1 result=0
  provider_main "$stage" yoyopod-dev.service yoyopod-prod.service > "$stage/stdout" || result=$?
  [[ "$result" == "$expected" ]] || { echo "unexpected transaction status $result expected $expected" >&2; cat "$trace" >&2; exit 1; }
}

for point in verify-stage require-dev-no-calls capture-prior no-calls; do
  case_stage "preflight-$point"; fail_at=$point
  run_failure 1
  ! grep -Eq '^(stop-native|stop-provider|install-candidate)$' "$trace"
  [[ $(cat "$stage/packages") == old && $(cat "$stage/config") == old && $(cat "$stage/rust") == old ]]
done
echo 'PASS staging/call-lane/capture rejection leaves native/provider untouched'

for point in stop-native stop-provider; do
  case_stage "$point"; fail_at=$point
  run_failure 2
  ! grep -Fxq install-candidate "$trace"
  jq -e --arg point "$point" '.outcome=="recovery_required" and
    (if $point=="stop-native" then .native_stop_proven==false else .provider_stop_proven==false end)' "$stage/recovery.json" >/dev/null
done
echo 'PASS unproved service stop prevents package mutation with honest recovery'

case_stage owner-replaced-after-stop; replace_after_stop=true
run_failure 2
! grep -Eq '^(stop-provider|install-candidate)$' "$trace"
jq -e '.native_stop_proven==true and .provider_stop_proven==false' "$stage/recovery.json" >/dev/null
echo 'PASS actual transaction refuses replacement-owner empty evidence after native stop'

for point in install-candidate start-provider verify-provider-init start-native verify-native-expected; do
  case_stage "rollback-$point"; fail_at=$point
  run_failure 1
  [[ $(cat "$stage/packages") == old && $(cat "$stage/config") == old && $(cat "$stage/rust") == old ]]
  jq -e '.outcome=="rolled_back"' "$stage/outcome.json" >/dev/null
  ! test -e "$stage/recovery.json"
done
echo 'PASS partial install/init/selection/native failures restore consistent prior closure/config/Rust'

case_stage failed-rollback; fail_at=install-candidate; rollback_fails=true
run_failure 2
! grep -Fxq start-native "$trace"
[[ $(grep -Fxc stop-native "$trace") -ge 3 && $(grep -Fxc stop-provider "$trace") -ge 3 ]]
jq -e --argjson prior "$old_identity" '.outcome=="recovery_required" and .phase=="rollback"
  and .prior_identity==$prior and .native_stop_proven==true and .provider_stop_proven==true' "$stage/recovery.json" >/dev/null
[[ $(stat -c %a "$stage/recovery.json") == 600 ]]
echo 'PASS failed rollback retains real durable recovery record and never starts mixed native'

case_stage unproved-rollback-stops; fail_at=install-candidate; rollback_stop_fails=true
run_failure 2
! grep -Eq '^(restore-prior-packages|start-native)$' "$trace"
jq -e '.outcome=="recovery_required" and .native_stop_proven==false and .provider_stop_proven==false' "$stage/recovery.json" >/dev/null
echo 'PASS rollback attempts both stops and never claims unproved stopped state'

case_stage interruption; signal_at=install-candidate
run_failure 2
[[ $(cat "$stage/packages") == old && $(cat "$stage/config") == old && $(cat "$stage/rust") == old ]]
jq -e '.outcome=="rolled_back"' "$stage/outcome.json" >/dev/null
echo 'PASS actual TERM trap restores coherent prior bytes after partial install'

case_stage pending-success
provider_main "$stage" yoyopod-dev.service yoyopod-prod.service > "$stage/stdout"
jq -e '.schema_version==1 and .outcome=="installed_qualification_pending"' "$stage/outcome.json" >/dev/null
jq -e '.phase=="installed"' "$stage/journal.json" >/dev/null
! grep -Eq '^restore-prior-' "$trace"
[[ $(cat "$stage/packages") == new && $(cat "$stage/config") == new && $(cat "$stage/rust") == new ]]
echo 'PASS valid synthetic installation pending is distinct successful outcome, never audio qualification'

for point in installed-phase install-outcome rollback-outcome running-final-stop-fail; do
  case_stage "durable-$point"
  (
    start_native() { [[ "$native_stopped" == false ]]; effect start-native; }
    verify_native_expected() {
      effect verify-native-expected || return
      outcome=installed_qualification_pending
      if [[ "$point" == installed-phase ]]; then rm -- "$stage/journal.json"; mkdir -- "$stage/journal.json"
      elif [[ "$point" == install-outcome || "$point" == running-final-stop-fail || "$restoring" == true ]]; then mkdir -- "$stage/outcome.json"; fi
      if [[ "$point" == running-final-stop-fail ]]; then stop_fails=true; fi
    }
    if [[ "$point" == rollback-outcome ]]; then fail_at=install-candidate; fi
    run_failure 2
    [[ -d "$stage/outcome.json" || ! -e "$stage/outcome.json" ]]
    [[ $(grep -Fxc stop-native "$trace") -ge 2 && $(grep -Fxc stop-provider "$trace") -ge 2 ]]
    if [[ "$point" == running-final-stop-fail ]]; then
      jq -e '.outcome=="recovery_required" and .native_stop_proven==false and .provider_stop_proven==false' "$stage/recovery.json" >/dev/null
    else jq -e '.outcome=="recovery_required" and .native_stop_proven==true and .provider_stop_proven==true' "$stage/recovery.json" >/dev/null; fi
  )
done
echo 'PASS real final phase/outcome writer failures stop both services and retain truthful durable recovery'

(
  source "$transaction"
  provider_identity() { printf '%s\n' "$new_identity"; }
  provider_no_calls() { echo borrowed-owner > "$stage/borrowed-owner"; }
  systemctl() { echo stopped-replacement > "$stage/stopped-replacement"; }
  ! stop_provider "$old_identity"
  [[ ! -e "$stage/borrowed-owner" && ! -e "$stage/stopped-replacement" ]]
)
echo 'PASS real provider-stop effect rejects a replacement before empty Calls or stop can be borrowed'

(
  source "$transaction"
  logs=$(jq -cn '{__MONOTONIC_TIMESTAMP:"2000000",MESSAGE:"GSM availability pid=123 available=false"}';
    jq -cn '{__MONOTONIC_TIMESTAMP:"2000001",MESSAGE:"GSM provider audio unavailable: GSM provider installed, qualification pending pid=123"}')
  provider_pending_result 123 100 100 <<< "$logs"
  logs+=$'\n'$(jq -cn '{__MONOTONIC_TIMESTAMP:"2000002",MESSAGE:"GSM provider audio unavailable: receipt identity mismatch pid=123"}')
  ! provider_pending_result 123 100 100 <<< "$logs"
  logs+=$'\n'$(jq -cn '{__MONOTONIC_TIMESTAMP:"2000003",MESSAGE:"GSM provider audio unavailable: GSM provider installed, qualification pending pid=999"}')
  ! provider_pending_result 123 100 100 <<< "$logs"
)
echo 'PASS actual pending-result selector rejects a later same-bool failure and unrelated worker evidence'

(
  source "$transaction"
  for tool in getfacl setfacl getfattr setfattr; do command -v "$tool" >/dev/null; done
  metadata_stage="$fixture_root/actual-metadata"
  mkdir -p -- "$metadata_stage/prior/rust/device/runtime/build" "$metadata_stage/candidate" "$metadata_stage/checkout/device/runtime/build" "$metadata_stage/checkout/config"
  checkout="$metadata_stage/checkout"; service_user=$(id -un); restoring=true
  printf '%s\n' '{"binaries":[{"file":"device/runtime/build/yoyopod-runtime"}]}' > "$metadata_stage/candidate/manifest.json"
  binary="$checkout/device/runtime/build/yoyopod-runtime"
  printf old > "$binary"; chmod 0750 "$binary" "$checkout/device/runtime/build" "$checkout"
  provider_capture_rust_metadata "$metadata_stage"
  cp -a -- "$binary" "$metadata_stage/prior/rust/device/runtime/build/yoyopod-runtime"
  setfacl -m u:65534:r-- "$binary"
  ! provider_capture_rust_metadata "$metadata_stage"
  setfacl -b "$binary"; chmod 0750 "$binary"
  setfattr -n user.yoyopod-test -v prior "$binary"
  ! provider_capture_rust_metadata "$metadata_stage"
  setfattr -x user.yoyopod-test "$binary"
  setfacl -m d:u:65534:r-x "$checkout/config"
  ! provider_config_restorable "$checkout/config" "$service_user"
  setfacl -b -k "$checkout/config"
  setfattr -n user.yoyopod-test -v prior "$checkout/config"
  ! provider_config_restorable "$checkout/config" "$service_user"
  setfattr -x user.yoyopod-test "$checkout/config"
  provider_config_restorable "$checkout/config" "$service_user"
  printf config-old > "$checkout/config/settings"
  chmod 0640 "$checkout/config/settings"; chmod 0750 "$checkout/config"
  provider_config_metadata "$checkout/config" > "$metadata_stage/prior/config-metadata"
  cp -a -- "$checkout/config" "$metadata_stage/prior/config"
  provider_capture_rust_metadata "$metadata_stage"
  grep -Fxq $'.\t750' "$metadata_stage/prior/rust-metadata"
  printf new > "$binary"; chmod 0755 "$binary" "$checkout/device/runtime/build" "$checkout"
  # Only the account-switch effect is replaced: execute as this same service UID.
  runuser() { [[ "$1" == -u && "$2" == "$service_user" && "$3" == -- ]]; shift 3; "$@"; }
  provider_copy_rust "$metadata_stage" "$metadata_stage/prior/rust"
  provider_restore_rust_metadata "$metadata_stage"
  printf config-new > "$checkout/config/settings"; chmod 0600 "$checkout/config/settings"; chmod 0700 "$checkout/config"
  provider_restore_config "$metadata_stage"
  [[ $(cat "$binary") == old && $(stat -c %a "$binary") == 750 && $(stat -c %a "$checkout/device/runtime/build") == 750 && $(stat -c %a "$checkout") == 750 ]]
  [[ $(cat "$checkout/config/settings") == config-old && $(stat -c %a "$checkout/config/settings") == 640 && $(stat -c %a "$checkout/config") == 750 ]]
  provider_metadata_supported "$binary" "$service_user"
)
echo 'PASS actual metadata guards refuse file/directory ACLs and xattrs; supported Rust bytes/0750 and parent mode restore exactly'

(
  source "$transaction"
  modem_stage="$fixture_root/actual-modem"
  mkdir -p -- "$modem_stage/candidate/providers/modemmanager"
  cp -- "$provider_root/profile.json" "$modem_stage/candidate/providers/modemmanager/profile.json"
  provider_stage=$modem_stage; modem_mode=valid
  provider_bus() {
    local property=${5:-} key value
    if [[ "$1" == call ]]; then
      if [[ "$modem_mode" == ambiguous ]]; then printf '%s\n' '{"data":[{"/org/freedesktop/ModemManager1/Modem/0":{},"/org/freedesktop/ModemManager1/Modem/1":{}}]}'
      else printf '%s\n' '{"data":[{"/org/freedesktop/ModemManager1/Modem/0":{}}]}'; fi
      return
    fi
    case "$property" in
      Manufacturer) key=manufacturer;; Model) key=model;; Revision) key=revision;; HardwareRevision) key=hardware_revision;; Plugin) key=plugin;;
      State) printf '%s\n' '{"data":[6]}'; return;; UnlockRequired) printf '%s\n' '{"data":[1]}'; return;;
      EmergencyOnly) printf '%s\n' '{"data":[false]}'; return;; PrimaryPort) printf '%s\n' '{"data":["cdc-wdm0"]}'; return;;
      Ports) printf '%s\n' '{"data":[[["cdc-wdm0",6]]]}'; return;; *) return 1;;
    esac
    value=$(jq -r --arg key "$key" '.modem[$key]' "$modem_stage/candidate/providers/modemmanager/profile.json")
    if [[ "$property" == Revision && "$modem_mode" == wrong-firmware ]]; then value=other-firmware; fi
    jq -cn --arg value "$value" '{data:[$value]}'
  }
  provider_identity() { printf '%s\n' "$old_identity"; }
  provider_no_calls() { :; }
  before_identity=$old_identity
  before_modem=$(provider_current_modem :1.10)
  provider_pre_stop
  verify_stage() { :; }
  require_dev_no_calls() { before_identity=$old_identity; before_modem=$(provider_current_modem :1.10); }
  capture_prior() { if [[ "$modem_mode" == staged-change ]]; then modem_mode=wrong-firmware; fi; }
  stop_native() { : > "$modem_stage/stopped"; }
  stop_provider() { : > "$modem_stage/stopped"; }
  install_candidate() { : > "$modem_stage/installed"; }
  for modem_mode in wrong-firmware ambiguous staged-change; do
    # staged-change first captures a valid proof, then changes only its read effect.
    if [[ "$modem_mode" == staged-change ]]; then
      require_dev_no_calls() { before_identity=$old_identity; modem_mode=valid; before_modem=$(provider_current_modem :1.10); modem_mode=staged-change; }
    fi
    ! provider_main "$modem_stage" yoyopod-dev.service yoyopod-prod.service
    [[ ! -e "$modem_stage/stopped" && ! -e "$modem_stage/installed" ]]
  done
)
echo 'PASS actual modem/profile proof rejects wrong firmware, ambiguous inventory and staging change before either stop'

(
  source "$transaction"
  init_stage="$fixture_root/actual-restored-init"
  mkdir -p -- "$init_stage/prior/files/var/lib/yoyopod/providers/modemmanager"
  printf '%s\n' "$old_identity" > "$init_stage/prior/identity.json"
  printf '%s\n' aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa > "$init_stage/prior/provider-invocation"
  restored=$(jq -c '.package_version="1.24.0-1+deb13u1+yoyopod1"' <<< "$new_identity")
  jq -cn '{daemon_sha256:"synthetic-new"}' > "$init_stage/prior/files/var/lib/yoyopod/providers/modemmanager/manifest.json"
  provider_identity() { printf '%s\n' "$restored"; }
  provider_no_calls() { :; }
  systemctl() { printf '%s\n' bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; }
  provider_current_modem() { printf '/org/freedesktop/ModemManager1/Modem/0\n'; }
  init_mode=failed
  provider_latest_init() {
    if [[ "$init_mode" == failed ]]; then printf '[modem0] voice-audio contract=1 generation=2 operation=9 selection=ok readback=failed\n'
    else printf '[modem0] voice-audio contract=1 generation=2 operation=9 selection=ok readback=ok\n'; fi
  }
  ! provider_verify_restored_init "$init_stage" "$restored"
  init_mode=ok
  provider_verify_restored_init "$init_stage" "$restored"
  restored=$(jq -c '.package_version="1.24.0-1+deb13u1"' <<< "$restored")
  provider_verify_restored_init "$init_stage" "$restored"
  sleep() { :; }
  provider_current_modem() { return 1; }
  ! provider_verify_restored_init "$init_stage" "$restored"
)
echo 'PASS actual restored-init guard requires fresh patched readback and affirmative stock initialization independently of hash/Calls'

(
  source "$transaction"
  apt_stage="$fixture_root/actual-apt-guards"
  mkdir -- "$apt_stage"
  printf 'original status\n' > "$apt_stage/live-status"
  printf 'package install\n' > "$apt_stage/live-selections"
  cp -- "$apt_stage/live-status" "$apt_stage/apt-forward-status.expected"
  cp -- "$apt_stage/live-selections" "$apt_stage/apt-forward-selections.expected"
  printf 'modemmanager 1 arm64 none < 2 arm64 none /protected/modemmanager.deb\n' > "$apt_stage/apt-forward-plan.expected"
  provider_package_status() { cat "$apt_stage/live-status"; }
  provider_package_selections() { cat "$apt_stage/live-selections"; }
  fuser() { [[ "$contention" == true ]]; }
  DPKG_FRONTEND_LOCKED=true; APT_HOOK_INFO_FD=0; contention=false
  provider_apt_status_guard "$apt_stage" forward
  input=$'VERSION 3\nAPT::Architecture=arm64\n\nmodemmanager 1 arm64 none < 2 arm64 none /protected/modemmanager.deb'
  printf '%s\n' "$input" | provider_apt_plan_guard "$apt_stage" forward
  [[ -f "$apt_stage/apt-forward-entered.json" ]]
  rm -- "$apt_stage/apt-forward-entered.json"
  printf '%s\n' "${input/modemmanager /unrelated }" | { ! provider_apt_plan_guard "$apt_stage" forward; }
  printf '%s\n' "${input/< 2 /< 3 }" | { ! provider_apt_plan_guard "$apt_stage" forward; }
  printf '%s\n' "${input/VERSION 3/VERSION 2}" | { ! provider_apt_plan_guard "$apt_stage" forward; }
  [[ ! -e "$apt_stage/apt-forward-entered.json" ]]
  printf 'external status\n' > "$apt_stage/live-status"
  ! provider_apt_status_guard "$apt_stage" forward
  printf '%s\n' "$input" | { ! provider_apt_plan_guard "$apt_stage" forward; }
  [[ ! -e "$apt_stage/apt-forward-entered.json" ]]
  cp -- "$apt_stage/apt-forward-status.expected" "$apt_stage/live-status"
  contention=true
  ! provider_apt_status_guard "$apt_stage" forward
  contention=false
  printf '%s\n' "$input" | provider_apt_plan_guard "$apt_stage" forward
  printf 'our partial status\n' > "$apt_stage/live-status"
  provider_apt_post "$apt_stage" forward
  provider_apt_after_matches "$apt_stage" forward
  cp -- "$apt_stage/apt-forward-status.after" "$apt_stage/apt-rollback-status.expected"
  cp -- "$apt_stage/apt-forward-selections.after" "$apt_stage/apt-rollback-selections.expected"
  printf 'external unrelated change\n' > "$apt_stage/live-status"
  ! provider_apt_after_matches "$apt_stage" forward
  ! provider_apt_status_guard "$apt_stage" rollback
  rm -- "$apt_stage/apt-forward-post.json"
  ! provider_apt_after_matches "$apt_stage" forward
)
echo 'PASS actual APT guards reject changed plan/status/contention and require protected post-attempt evidence for rollback'

for state in conflict uncertain; do
  case_stage "no-stale-rollback-$state"
  (
    install_candidate() { record install-candidate; package_attempt_state=$state; printf external > "$stage/packages"; return 1; }
    provider_restore_temporary_policy() { record restore-temporary-policy; }
    run_failure 2
    [[ $(cat "$stage/packages") == external ]]
    ! grep -Eq '^(restore-prior-packages|restore-prior-service|restore-prior-rust|start-native)$' "$trace"
    jq -e '.outcome=="recovery_required" and .native_stop_proven==true and .provider_stop_proven==true' "$stage/recovery.json" >/dev/null
  )
done
echo 'PASS actual orchestration never rolls a stale snapshot over external or unproved package mutations'
