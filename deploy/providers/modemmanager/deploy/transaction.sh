#!/usr/bin/env bash
# Embedded fixed maintenance program. Sourcing only defines functions.
provider_json_write() {
  local file=$1 json=$2 temporary
  [[ ! -d "$file" && ! -L "$file" ]] || return 1
  temporary=$(mktemp "${file}.XXXXXXXXXXXX") || return
  printf '%s\n' "$json" > "$temporary" && chmod 0600 "$temporary" && sync -f "$temporary" \
    && mv -fT -- "$temporary" "$file" && sync -f "$(dirname -- "$file")"
}
write_recovery_record() {
  local stage=$1 prior=null record
  if [[ -f "$stage/prior/identity.json" ]]; then prior=$(cat "$stage/prior/identity.json") || return; fi
  record=$(jq -cn --arg phase "${phase:-unknown}" --arg reason "${failure_reason:-transaction failed}" \
    --argjson prior "$prior" --argjson native_stopped "${native_stopped:-false}" \
    --argjson provider_stopped "${provider_stopped:-false}" \
    '{schema_version:1,outcome:"recovery_required",phase:$phase,reason:$reason,prior_identity:$prior,
      native_stop_proven:$native_stopped,provider_stop_proven:$provider_stopped}') || return
  provider_json_write "$stage/recovery.json" "$record"
}
provider_phase() {
  phase=$2
  provider_json_write "$1/journal.json" "$(jq -cn --arg phase "$phase" '{schema_version:1,phase:$phase}')"
}
provider_protected_directory() {
  local path=$1 component=/ part mode
  local -a parts=()
  [[ "$path" == /* && "$path" != *'/../'* && "$path" != *'/./'* ]] || return 1
  IFS=/ read -r -a parts <<< "$path"
  for part in "${parts[@]}"; do
    [[ -n "$part" ]] || continue
    component="${component%/}/$part"
    [[ -d "$component" && ! -L "$component" && $(stat -c %u "$component") == 0 ]] || return 1
    mode=$(stat -c %a "$component") || return
    (( (8#$mode & 0022) == 0 )) || return 1
  done
}
provider_migrate_common_parent() {
  local dev=$1 path=/var/lib/yoyopod user uid owner mode existing
  provider_protected_directory /var/lib || return
  if [[ ! -e "$path" && ! -L "$path" ]]; then install -d -m 0755 -o root -g root "$path"; return; fi
  [[ -d "$path" && ! -L "$path" ]] || return 1
  user=$(systemctl show -p User --value "$dev") || return
  user=${user:-root}
  [[ "$user" =~ ^[a-zA-Z0-9_-]+$ ]] || return 1
  uid=$(id -u "$user") || return
  owner=$(stat -c %u "$path"); mode=$(stat -c %a "$path")
  [[ "$owner" == 0 || ( "$owner" == "$uid" && ( "$mode" == 750 || "$mode" == 755 ) ) ]] || return 1
  # Change only the legacy common parent. Existing provider descendants must
  # already be protected root objects; never chown attacker-created proof.
  for existing in "$path/providers" "$path/providers/modemmanager" "$path/providers/modemmanager/transactions"; do
    if [[ -e "$existing" || -L "$existing" ]]; then
      [[ -d "$existing" && ! -L "$existing" && $(stat -c %u "$existing") == 0 ]] || return 1
      mode=$(stat -c %a "$existing") || return
      (( (8#$mode & 0022) == 0 )) || return 1
    fi
  done
  for existing in "$path/providers/modemmanager/installed.json" "$path/providers/modemmanager/manifest.json" "$path/providers/modemmanager/profile.json"; do
    if [[ -e "$existing" || -L "$existing" ]]; then
      [[ -f "$existing" && ! -L "$existing" && $(stat -c %u "$existing") == 0 ]] || return 1
      mode=$(stat -c %a "$existing") || return
      (( (8#$mode & 0022) == 0 )) || return 1
    fi
  done
  chown root:root "$path" && chmod 0755 "$path" && provider_protected_directory "$path"
}
provider_bus() { timeout --signal=TERM --kill-after=2s 10s busctl --system --json=short "$@"; }
provider_owner() {
  provider_bus call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus GetNameOwner s org.freedesktop.ModemManager1 \
    | jq -er '.data | if length==1 and (.[0]|type=="string" and startswith(":")) then .[0] else error("owner") end'
}
provider_absent() {
  provider_bus call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus NameHasOwner s org.freedesktop.ModemManager1 \
    | jq -e '.data==[false]' >/dev/null
}
provider_ticks() { sed 's/^.*) //' "/proc/$1/stat" | awk '{print $20}'; }
provider_process_executable() {
  local process=$1 executable comm
  if executable=$(readlink -- "$process/exe" 2>/dev/null); then
    executable=${executable% (deleted)}
    printf '%s\n' "${executable##*/}"
    return
  fi
  # Exited processes/kernel threads have no executable. A relevant still-live
  # process whose executable cannot be read is uncertainty, not proof of absence.
  comm=$(cat "$process/comm" 2>/dev/null) || return 1
  case "$comm" in yoyopod-*|ModemManager) return 2;; *) return 1;; esac
}
provider_identity() {
  local owner pid bus ticks running installed version architecture again
  owner=$(provider_owner) || return
  pid=$(provider_bus call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus GetConnectionUnixProcessID s "$owner" | jq -er '.data[0]') || return
  [[ "$pid" =~ ^[1-9][0-9]*$ && $(systemctl show -p MainPID --value ModemManager.service) == "$pid" ]] || return 1
  bus=$(provider_bus call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus GetId | jq -er '.data[0]') || return
  ticks=$(provider_ticks "$pid") || return
  [[ "$ticks" =~ ^[1-9][0-9]*$ ]] || return 1
  running=$(sha256sum "/proc/$pid/exe" | cut -d ' ' -f 1) || return
  installed=$(sha256sum /usr/sbin/ModemManager | cut -d ' ' -f 1) || return
  version=$(dpkg-query -W -f='${Version}' modemmanager) || return
  architecture=$(dpkg-query -W -f='${Architecture}' modemmanager) || return
  again=$(provider_owner) || return
  [[ "$again" == "$owner" && $(provider_ticks "$pid") == "$ticks" && "$running" == "$installed" ]] || return 1
  jq -cn --arg bus "$bus" --arg owner "$owner" --argjson pid "$pid" --argjson ticks "$ticks" \
    --arg running "$running" --arg installed "$installed" --arg version "$version" --arg architecture "$architecture" \
    '{bus_id:$bus,unique_owner:$owner,pid:$pid,process_start_ticks:$ticks,running_daemon_sha256:$running,
      installed_executable_sha256:$installed,package_version:$version,architecture:$architecture}'
}
provider_no_calls() {
  local expected=$1 objects modem calls call state
  local -a modems=()
  [[ $(provider_owner) == "$expected" ]] || return 1
  objects=$(provider_bus call "$expected" /org/freedesktop/ModemManager1 org.freedesktop.DBus.ObjectManager GetManagedObjects) || return
  jq -e '.data[0]|type=="object"' <<< "$objects" >/dev/null || return
  mapfile -t modems < <(jq -r '.data[0]|keys[]|select(test("^/org/freedesktop/ModemManager1/Modem/[0-9]+$"))' <<< "$objects")
  [[ ${#modems[@]} -gt 0 ]] || return 1
  for modem in "${modems[@]}"; do
    calls=$(provider_bus get-property "$expected" "$modem" org.freedesktop.ModemManager1.Modem.Voice Calls) || return
    jq -e '.data[0]|type=="array"' <<< "$calls" >/dev/null || return
    while IFS= read -r call; do
      [[ "$call" =~ ^/org/freedesktop/ModemManager1/Call/[0-9]+$ ]] || return 1
      state=$(provider_bus get-property "$expected" "$call" org.freedesktop.ModemManager1.Call State | jq -er '.data[0]') || return
      [[ "$state" == 7 ]] || return 1
    done < <(jq -r '.data[0][]' <<< "$calls")
  done
  [[ $(provider_owner) == "$expected" ]]
}
verify_stage() {
  local stage=$1 actual expected file name version architecture tool
  for tool in jq busctl systemctl dpkg dpkg-query dpkg-deb apt-get apt-cache git flock fuser runuser journalctl udevadm sha256sum timeout sed awk tar getconf install stat realpath sync find pgrep getfacl getfattr; do
    command -v "$tool" >/dev/null || return 1
  done
  [[ $(id -u) == 0 ]] && provider_protected_directory "$stage" || return 1
  [[ -z $(find -P "$stage" -mindepth 1 ! -type f ! -type d -print -quit) ]] || return 1
  [[ $(sha256sum "$stage/inputs.sha256" | cut -d ' ' -f 1) == "$expected_inputs" ]] || return 1
  (cd -- "$stage" && sha256sum --check --strict inputs.sha256) >&2 || return
  expected=$(sed 's/^[0-9a-f]\{64\}  //' "$stage/inputs.sha256" | LC_ALL=C sort) || return
  actual=$(cd -- "$stage" && find . -type f ! -name inputs.sha256 -printf '%P\n' | LC_ALL=C sort) || return
  [[ "$actual" == "$expected" ]] || return 1
  jq -e 'keys==(["schema_version","repo_sha","ci_run_id","dev_checkout","branch","pid_file","log_file","startup_marker"]|sort)
    and .schema_version==1 and (.repo_sha|test("^[0-9a-f]{40}$")) and (.ci_run_id|test("^[0-9]+$"))
    and (.dev_checkout|startswith("/opt/yoyopod-dev/"))' "$stage/control.json" >/dev/null || return
  checkout=$(jq -er .dev_checkout "$stage/control.json") || return
  [[ $(basename -- "$(dirname -- "$stage")") == $(jq -r .repo_sha "$stage/control.json") ]] || return 1
  [[ "$checkout" == "$(realpath -e -- "$checkout")" && -d "$checkout/.git" ]] || return 1
  . /etc/os-release
  [[ "$ID" == debian && "$VERSION_CODENAME" == trixie && $(dpkg --print-architecture) == arm64 ]] || return 1
  [[ -z $(dpkg --audit) ]] && timeout 30s apt-get check >&2 || return 1
  ! fuser /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend /var/cache/apt/archives/lock >/dev/null 2>&1 || return 1
  git clone --mirror -- "$stage/repository.bundle" "$stage/repository.git" >&2 || return
  find "$stage/repository.git" -type d -exec chmod 0755 {} + || return
  find "$stage/repository.git" -type f -exec chmod 0644 {} + || return
  git --git-dir="$stage/repository.git" cat-file -e "$(jq -r .repo_sha "$stage/control.json")^{commit}" || return
  jq -e --slurpfile root "$stage/candidate/manifest.json" '.repo_sha==$root[0].repo_sha and .ci_run_id==$root[0].ci_run_id
    and .architecture=="arm64"' "$stage/candidate/providers/modemmanager/manifest.json" >/dev/null || return
  while IFS=$'\t' read -r file name version architecture; do
    [[ $(dpkg-deb -f "$stage/candidate/providers/modemmanager/$file" Package) == "$name"
      && $(dpkg-deb -f "$stage/candidate/providers/modemmanager/$file" Version) == "$version"
      && $(dpkg-deb -f "$stage/candidate/providers/modemmanager/$file" Architecture) == "$architecture" ]] || return 1
  done < <(jq -r '.packages[]|[.file,.name,.version,.architecture]|@tsv' "$stage/candidate/providers/modemmanager/manifest.json")
  file=$(jq -er '.packages[]|select(.name=="modemmanager")|.file' "$stage/candidate/providers/modemmanager/manifest.json") || return
  actual=$(dpkg-deb --fsys-tarfile "$stage/candidate/providers/modemmanager/$file" | tar -xOf - ./usr/sbin/ModemManager | sha256sum | cut -d ' ' -f 1) || return
  [[ "$actual" == $(jq -er .daemon_sha256 "$stage/candidate/providers/modemmanager/manifest.json") ]]
}
require_dev_no_calls() {
  local dev=$1 prod=$2 pid group process executable identity
  systemctl is-active --quiet "$dev" && ! systemctl is-active --quiet "$prod" || return 1
  pid=$(systemctl show -p MainPID --value "$dev") || return
  [[ "$pid" =~ ^[1-9][0-9]*$ && $(readlink -e "/proc/$pid/cwd") == "$checkout" ]] || return 1
  group=$(systemctl show -p ControlGroup --value "$dev") || return
  [[ -n "$group" ]] || return 1
  for process in /proc/[0-9]*; do
    if executable=$(provider_process_executable "$process"); then :; else [[ $? == 1 ]] && continue; return 1; fi
    case "${executable##*/}" in yoyopod-runtime|yoyopod-*-host|yoyopod-on-pi) grep -Fxq "0::$group" "$process/cgroup" || return 1;; esac
  done
  service_user=$(systemctl show -p User --value "$dev") || return
  service_user=${service_user:-root}
  [[ "$service_user" =~ ^[a-zA-Z0-9_-]+$ ]] || return 1
  identity=$(provider_identity) || return
  for process in /proc/[0-9]*; do
    if executable=$(provider_process_executable "$process"); then :; else [[ $? == 1 ]] && continue; return 1; fi
    if [[ "${executable##*/}" == ModemManager && ${process##*/} != $(jq -r .pid <<< "$identity") ]]; then return 1; fi
  done
  provider_no_calls "$(jq -r .unique_owner <<< "$identity")" || return
  runuser -u "$service_user" -- test -r "/proc/$(jq -r .pid <<< "$identity")/stat" || return
  runuser -u "$service_user" -- sha256sum /usr/sbin/ModemManager >/dev/null || return
  before_identity=$identity
  before_modem=$(provider_current_modem "$(jq -r .unique_owner <<< "$identity")") || return
  [[ $(provider_identity) == "$before_identity" ]] || return 1
}

provider_backup_path() {
  local stage=$1 path=$2 destination="$1/prior/files$2" parent
  [[ "$path" == /etc/* || "$path" == /run/systemd/system/ModemManager.service.d \
    || "$path" == /usr/sbin/policy-rc.d || "$path" == /var/lib/yoyopod/providers/modemmanager/*.json ]] || return 1
  [[ "$path" != *'/../'* && "$path" != *'/./'* && "$path" != *'//'*
    && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || return 1
  parent=$(dirname -- "$path") || return
  while [[ ! -e "$parent" && ! -L "$parent" ]]; do parent=$(dirname -- "$parent") || return; done
  provider_protected_directory "$parent" || return
  mkdir -p -- "$(dirname -- "$destination")" || return
  if [[ -e "$path" || -L "$path" ]]; then cp -a -- "$path" "$destination" || return; fi
}
provider_simulation() {
  local stage=$1 mode=$2 status=$3 log="$1/prior/$2-simulation.log" name line
  local -a packages=() removals=() options=()
  if [[ "$mode" == forward ]]; then
    mapfile -t packages < <(jq -r '.packages[].file' "$stage/candidate/providers/modemmanager/manifest.json" | sed "s|^|$stage/candidate/providers/modemmanager/|")
  else
    mapfile -t packages < <(find "$stage/prior/packages" -type f -name '*.deb' -print | LC_ALL=C sort)
    while IFS= read -r name; do removals+=("$name-"); done < "$stage/prior/additions"
    options=(-o "Dir::State::status=$status")
  fi
  timeout --signal=TERM --kill-after=5s 60s apt-get -s --no-download --no-install-recommends --purge \
    "${options[@]}" install -- "${packages[@]}" "${removals[@]}" > "$log" 2>&1 || return
  while IFS= read -r line; do
    case "$line" in
      'Inst '*|'Remv '*)
        name=${line#* }; name=${name%% *}; name=${name%%:*}
        grep -Fxq "$name" "$stage/prior/allowed" || return 1
        if [[ "$mode" == forward && "$line" == 'Remv '* ]]; then return 1; fi ;;
    esac
  done < "$log"
}
provider_prior_archive() {
  local stage=$1 name=$2 version=$3 architecture=$4 expected='' signed='' file digest receipt=/var/lib/yoyopod/providers/modemmanager
  if [[ -f "$receipt/installed.json" && -f "$receipt/manifest.json" && ! -L "$receipt/installed.json" && ! -L "$receipt/manifest.json" ]]; then
    if [[ $(stat -c %u "$receipt/installed.json") == 0 && $(stat -c %u "$receipt/manifest.json") == 0 \
      && $(sha256sum "$receipt/manifest.json" | cut -d ' ' -f 1) == $(jq -r .manifest_sha256 "$receipt/installed.json") ]]; then
      expected=$(jq -r --arg name "$name" --arg version "$version" --arg architecture "$architecture" \
        '.packages[]|select(.name==$name and .version==$version and .architecture==$architecture)|.sha256' "$receipt/manifest.json") || return
    fi
  fi
  signed=$(apt-cache show "$name:$architecture=$version" 2>/dev/null | sed -n 's/^SHA256: //p') || signed=''
  for file in "$stage/candidate/providers/modemmanager/packages/"*.deb /var/cache/apt/archives/*.deb; do
    [[ -f "$file" && ! -L "$file" ]] || continue
    digest=$(sha256sum "$file" | cut -d ' ' -f 1) || return
    if [[ "$digest" == "$expected" ]] || grep -Fxq "$digest" <<< "$signed"; then
      if [[ $(dpkg-deb -f "$file" Package) == "$name" && $(dpkg-deb -f "$file" Version) == "$version" \
        && $(dpkg-deb -f "$file" Architecture) == "$architecture" ]]; then
        cp -- "$file" "$stage/prior/packages/$name.deb"; return $?
      fi
    fi
  done
  mkdir -m 0700 -- "$stage/prior/download-$name" || return
  (cd -- "$stage/prior/download-$name" && timeout 90s apt-get download "$name:$architecture=$version") >&2 || return
  for file in "$stage/prior/download-$name/"*.deb; do
    [[ -f "$file" && ! -L "$file" ]] || continue
    if [[ $(dpkg-deb -f "$file" Package) == "$name" && $(dpkg-deb -f "$file" Version) == "$version" \
      && $(dpkg-deb -f "$file" Architecture) == "$architecture" ]]; then
      digest=$(sha256sum "$file" | cut -d ' ' -f 1) || return
      [[ "$digest" == "$expected" ]] || grep -Fxq "$digest" <<< "$signed" || return 1
      cp -- "$file" "$stage/prior/packages/$name.deb"; return $?
    fi
  done
  return 1
}
provider_metadata_supported() {
  local path=$1 user=$2 uid gid mode acl attributes
  uid=$(id -u "$user") && gid=$(id -g "$user") || return
  [[ ! -L "$path" && ( -f "$path" || -d "$path" ) \
    && $(stat -c %u "$path") == "$uid" && $(stat -c %g "$path") == "$gid" ]] || return 1
  mode=$(stat -c %a "$path") || return
  (( (8#$mode & 07000) == 0 )) || return 1
  acl=$(getfacl --absolute-names --omit-header --physical -- "$path") || return
  [[ $(printf '%s\n' "$acl" | sed '/^$/d' | wc -l) == 3 \
    && "$acl" == $'user::'* && "$acl" != *$'\ndefault:'* && "$acl" != *$'\nmask:'* ]] || return 1
  attributes=$(getfattr --absolute-names --dump --match=- -- "$path") || return
  [[ -z "$attributes" ]]
}
provider_config_restorable() {
  local directory=$1 user=$2 path mode
  [[ -d "$directory" && ! -L "$directory" ]] || return 1
  while IFS= read -r -d '' path; do
    provider_metadata_supported "$path" "$user" || return
    if [[ -d "$path" ]]; then
      mode=$(stat -c %a "$path") || return
      # The unprivileged restore must enumerate, remove and recreate entries.
      (( (8#$mode & 0700) == 0700 )) || return 1
    fi
  done < <(find -P "$directory" -print0)
}
provider_config_metadata() { find -P "$1" -printf '%P\t%y\t%U\t%G\t%m\0' | LC_ALL=C sort -z; }
provider_capture_rust_metadata() {
  local stage=$1 file path mode relative
  : > "$stage/prior/rust-metadata"
  while IFS= read -r file; do
    path="$checkout/$file"
    while [[ "$path" == "$checkout" || "$path" == "$checkout/"* ]]; do
      provider_metadata_supported "$path" "$service_user" || return
      mode=$(stat -c %a "$path") || return
      if [[ -d "$path" ]]; then (( (8#$mode & 0700) == 0700 )) || return 1; fi
      relative=${path#"$checkout"}
      [[ -n "$relative" ]] || relative=.
      printf '%s\t%s\n' "$relative" "$mode" >> "$stage/prior/rust-metadata"
      [[ "$path" != "$checkout" ]] || break
      path=$(dirname -- "$path") || return
    done
  done < <(jq -r '.binaries[].file' "$stage/candidate/manifest.json")
  LC_ALL=C sort -u "$stage/prior/rust-metadata" -o "$stage/prior/rust-metadata"
}
capture_prior() {
  local stage=$1 name version architecture state package identity file listing path known
  mkdir -m 0700 -- "$stage/prior" || return
  mkdir -m 0700 -- "$stage/prior/packages" "$stage/prior/files" "$stage/prior/rust" || return
  cp -- /var/lib/dpkg/status "$stage/prior/status" || return
  provider_package_selections > "$stage/prior/selections" || return
  : > "$stage/prior/additions"; : > "$stage/prior/installed.tsv"; : > "$stage/prior/paths.unsorted"
  jq -r '.packages[].name' "$stage/candidate/providers/modemmanager/manifest.json" | LC_ALL=C sort > "$stage/prior/allowed" || return
  while IFS= read -r name; do
    known=true
    state=$(dpkg-query -W -f='${db:Status-Status}' "$name" 2>/dev/null) || { state=not-installed; known=false; }
    if [[ "$state" == not-installed && "$known" == false ]]; then printf '%s\n' "$name" >> "$stage/prior/additions"; continue; fi
    [[ "$state" == installed ]] || { echo "provider staging: unresolved prior package state $name $state" >&2; return 1; }
    [[ $(dpkg-query -W -f='${db:Status-Want}' "$name") == install ]] || return 1
    version=$(dpkg-query -W -f='${Version}' "$name") || return
    architecture=$(dpkg-query -W -f='${Architecture}' "$name") || return
    printf '%s\t%s\t%s\n' "$name" "$version" "$architecture" >> "$stage/prior/installed.tsv"
    # Download while still fully staged/no-stop, using authenticated APT
    # metadata. The rollback never assumes this version remains online later.
    provider_prior_archive "$stage" "$name" "$version" "$architecture" || return
    dpkg-query -W -f='${Conffiles}\n' "$name" | sed -n 's/^ \(\/[^ ]*\) .*/\1/p' >> "$stage/prior/paths.unsorted" || return
  done < "$stage/prior/allowed"
  : > "$stage/prior/candidate-controls"
  while IFS= read -r file; do
    printf 'Status: install ok installed\n' >> "$stage/prior/candidate-controls"
    dpkg-deb -f "$stage/candidate/providers/modemmanager/$file" >> "$stage/prior/candidate-controls" || return
    printf '\n' >> "$stage/prior/candidate-controls"
    listing=$(dpkg-deb --ctrl-tarfile "$stage/candidate/providers/modemmanager/$file" | tar -tf -) || return
    if grep -Fxq ./conffiles <<< "$listing"; then
      dpkg-deb --ctrl-tarfile "$stage/candidate/providers/modemmanager/$file" | tar -xOf - ./conffiles \
        | sed 's/ remove-on-upgrade$//' >> "$stage/prior/paths.unsorted" || return
    fi
  done < <(jq -r '.packages[].file' "$stage/candidate/providers/modemmanager/manifest.json")
  awk 'BEGIN{RS="";ORS="\n\n"} function package(record,lines,n,i,name,arch){n=split(record,lines,"\n");for(i=1;i<=n;i++){if(lines[i]~/^Package: /)name=substr(lines[i],10);if(lines[i]~/^Architecture: /)arch=substr(lines[i],15)}return name ":" arch}
    NR==FNR{key=package($0);replacement[key]=$0;next}{key=package($0);if(key in replacement){print replacement[key];delete replacement[key]}else print}
    END{for(key in replacement)print replacement[key]}' "$stage/prior/candidate-controls" "$stage/prior/status" > "$stage/prior/simulated-candidate-status" || return
  provider_simulation "$stage" forward "$stage/prior/status" && provider_simulation "$stage" rollback "$stage/prior/simulated-candidate-status" || return
  printf '%s\n' /usr/sbin/policy-rc.d /etc/udev/rules.d/77-yoyopod-sim7600.rules \
    /etc/systemd/system/ModemManager.service.d /run/systemd/system/ModemManager.service.d /etc/default/ModemManager \
    /var/lib/yoyopod/providers/modemmanager/installed.json /var/lib/yoyopod/providers/modemmanager/manifest.json \
    /var/lib/yoyopod/providers/modemmanager/profile.json >> "$stage/prior/paths.unsorted"
  LC_ALL=C sort -u "$stage/prior/paths.unsorted" > "$stage/prior/paths" || return
  while IFS= read -r path; do provider_backup_path "$stage" "$path" || return; done < "$stage/prior/paths"
  [[ -z $(runuser -u "$service_user" -- git -C "$checkout" status --porcelain --untracked-files=no) ]] || return 1
  runuser -u "$service_user" -- git -C "$checkout" rev-parse HEAD > "$stage/prior/repo-sha" || return
  runuser -u "$service_user" -- git -C "$checkout" symbolic-ref -q --short HEAD > "$stage/prior/branch" || :
  provider_config_restorable "$checkout/config" "$service_user" || return
  provider_capture_rust_metadata "$stage" || return
  provider_config_metadata "$checkout/config" > "$stage/prior/config-metadata" || return
  cp -a -- "$checkout/config" "$stage/prior/config" || return
  while IFS= read -r file; do
    [[ -f "$checkout/$file" && ! -L "$checkout/$file" && -x "$checkout/$file" ]] || return 1
    mkdir -p -- "$stage/prior/rust/$(dirname -- "$file")" || return
    cp -a -- "$checkout/$file" "$stage/prior/rust/$file" || return
  done < <(jq -r '.binaries[].file' "$stage/candidate/manifest.json")
  (cd -- "$stage/prior" && find packages rust config files -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS) || return
  identity=$(provider_identity) || return
  [[ "$identity" == "$before_identity" && $(sha256sum /var/lib/dpkg/status | cut -d ' ' -f 1) == $(sha256sum "$stage/prior/status" | cut -d ' ' -f 1) ]] || return 1
  provider_no_calls "$(jq -r .unique_owner <<< "$identity")" || return
  provider_json_write "$stage/prior/identity.json" "$identity" || return
  file="$stage/prior/packages/modemmanager.deb"
  package=$(dpkg-deb --fsys-tarfile "$file" | tar -xOf - ./usr/sbin/ModemManager | sha256sum | cut -d ' ' -f 1) || return
  [[ "$package" == $(jq -r .running_daemon_sha256 <<< "$identity") ]] || return 1
  systemctl show -p UnitFileState --value ModemManager.service > "$stage/prior/provider-enabled" || return
  systemctl show -p InvocationID --value ModemManager.service > "$stage/prior/provider-invocation" || return
  case "$(cat "$stage/prior/provider-enabled")" in enabled|enabled-runtime|disabled|static|indirect) ;; *) return 1;; esac
  prior_ready=true
}
stop_native() {
  local dev=$1 executable process
  timeout --signal=TERM --kill-after=5s 45s systemctl stop "$dev" || return
  [[ $(systemctl show -p MainPID --value "$dev") == 0 && $(systemctl show -p ActiveState --value "$dev") == inactive ]] || return 1
  for process in /proc/[0-9]*; do
    if executable=$(provider_process_executable "$process"); then :; else [[ $? == 1 ]] && continue; return 1; fi
    case "${executable##*/}" in yoyopod-runtime|yoyopod-*-host|yoyopod-on-pi) return 1;; esac
  done
}
stop_provider() {
  local expected=$1 identity owner
  if identity=$(provider_identity); then
    [[ -n "$expected" && "$identity" == "$expected" ]] || return 1
    owner=$(jq -r .unique_owner <<< "$expected") || return
    provider_no_calls "$owner" && [[ $(provider_identity) == "$expected" ]] || return
  else
    provider_absent || return
    if [[ $(systemctl show -p MainPID --value ModemManager.service) != 0 ]]; then
      [[ -n "$expected" \
        && $(systemctl show -p MainPID --value ModemManager.service) == $(jq -r .pid <<< "$expected") \
        && $(provider_ticks "$(jq -r .pid <<< "$expected")") == $(jq -r .process_start_ticks <<< "$expected") \
        && $(sha256sum "/proc/$(jq -r .pid <<< "$expected")/exe" | cut -d ' ' -f 1) == $(jq -r .running_daemon_sha256 <<< "$expected") ]] || return 1
    fi
  fi
  timeout --signal=TERM --kill-after=5s 45s systemctl stop ModemManager.service || return
  [[ $(systemctl show -p MainPID --value ModemManager.service) == 0 \
    && $(systemctl show -p ActiveState --value ModemManager.service) == inactive ]] || return 1
  provider_absent || return
  ! pgrep -x ModemManager >/dev/null
}
provider_start_provider() {
  provider_stopped=false
  provider_start_attempted=true
  started_identity=''
  start_provider || return
  started_identity=$(provider_identity) || return
}
provider_start_native() { native_stopped=false; start_native "$1"; }
provider_stop_identity() {
  if [[ "${provider_start_attempted:-false}" == true ]]; then printf '%s\n' "${started_identity:-}"
  else printf '%s\n' "$before_identity"; fi
}
provider_pre_stop() {
  [[ $(provider_identity) == "$before_identity" ]] \
    && [[ $(provider_current_modem "$(jq -r .unique_owner <<< "$before_identity")") == "$before_modem" ]] \
    && provider_no_calls "$(jq -r .unique_owner <<< "$before_identity")" \
    && [[ $(provider_identity) == "$before_identity" ]]
}
provider_restore_enabled() {
  local enabled
  enabled=$(cat "$1/prior/provider-enabled") || return
  case "$enabled" in
    enabled) systemctl enable ModemManager.service >&2;;
    enabled-runtime) systemctl enable --runtime ModemManager.service >&2;;
    disabled) systemctl disable ModemManager.service >&2;;
    static|indirect) [[ $(systemctl show -p UnitFileState --value ModemManager.service) == "$enabled" ]];;
    *) return 1;;
  esac
}
provider_restore_temporary_policy() {
  local stage=$1 path prior
  for path in /usr/sbin/policy-rc.d /run/systemd/system/ModemManager.service.d; do
    rm -rf -- "$path" || return
    prior="$stage/prior/files$path"
    if [[ -e "$prior" || -L "$prior" ]]; then cp -a -- "$prior" "$path" || return; fi
  done
  systemctl daemon-reload && provider_restore_enabled "$stage"
}
provider_package_status() { cat /var/lib/dpkg/status; }
provider_package_selections() { dpkg --get-selections | LC_ALL=C sort; }
provider_status_row() {
  awk -v wanted="$2" 'BEGIN{RS=""} {name="";version="-";arch="-";multi="none";state="";n=split($0,lines,"\n");
    for(i=1;i<=n;i++){if(lines[i]~/^Package: /)name=substr(lines[i],10);if(lines[i]~/^Version: /)version=substr(lines[i],10);
      if(lines[i]~/^Architecture: /)arch=substr(lines[i],15);if(lines[i]~/^Multi-Arch: /)multi=substr(lines[i],13);if(lines[i]~/^Status: /)state=substr(lines[i],9)}
    if(name==wanted){if(multi=="no")multi="none";if(state=="install ok installed")print version,arch,multi;else print "- - none";found=1;exit}}
    END{if(!found)print "- - none"}' "$1"
}
provider_plan_expected() {
  local stage=$1 mode=$2 name operation ignored archive version arch multi old old_version comparison action
  : > "$stage/apt-$mode-plan.expected"
  while read -r operation name ignored; do
    case "$operation" in Inst|Conf|Remv) ;; *) continue;; esac
    name=${name%%:*}
    grep -Fxq "$name" "$stage/prior/allowed" || return 1
    old=$(provider_status_row "$stage/apt-$mode-status.expected" "$name") || return
    old_version=${old%% *}
    if [[ "$operation" == Remv ]]; then version=-; arch=-; multi=none; action='**REMOVE**'
    else
      if [[ "$mode" == forward ]]; then
        archive=$(jq -er --arg name "$name" '.packages[]|select(.name==$name)|.file' "$stage/candidate/providers/modemmanager/manifest.json") || return
        archive="$stage/candidate/providers/modemmanager/$archive"
      else archive="$stage/prior/packages/$name.deb"; fi
      version=$(dpkg-deb -f "$archive" Version) && arch=$(dpkg-deb -f "$archive" Architecture) && multi=$(dpkg-deb -f "$archive" Multi-Arch) || return
      multi=${multi:-none}; [[ "$multi" != no ]] || multi=none
      if [[ "$operation" == Conf ]]; then action='**CONFIGURE**'; else action=$archive; fi
    fi
    if [[ "$old_version" == "$version" ]]; then comparison='='
    elif [[ "$old_version" == - ]] || { [[ "$version" != - ]] && dpkg --compare-versions "$old_version" lt "$version"; }; then comparison='<'
    else comparison='>'; fi
    printf '%s %s %s %s %s %s %s\n' "$name" "$old" "$comparison" "$version" "$arch" "$multi" "$action" >> "$stage/apt-$mode-plan.expected"
  done < "$stage/prior/$mode-simulation.log"
}
provider_apt_status_guard() {
  local stage=$1 mode=$2 actual
  # APT itself owns the frontend lock when invoking these hooks. Honest direct
  # dpkg also takes that lock; never set DPKG_FRONTEND_LOCKED ourselves.
  [[ -n ${DPKG_FRONTEND_LOCKED:-} ]] || return 1
  ! fuser /var/lib/dpkg/lock >/dev/null 2>&1 || return 1
  actual=$(provider_package_status | sha256sum | cut -d ' ' -f 1) || return
  [[ "$actual" == $(sha256sum "$stage/apt-$mode-status.expected" | cut -d ' ' -f 1) ]] || return 1
  actual=$(provider_package_selections | sha256sum | cut -d ' ' -f 1) || return
  [[ "$actual" == $(sha256sum "$stage/apt-$mode-selections.expected" | cut -d ' ' -f 1) ]]
}
provider_apt_plan_guard() {
  local stage=$1 mode=$2 line expected index=0 boundary=false
  local -a columns=() rows=()
  [[ ${APT_HOOK_INFO_FD:-} == 0 ]] || return 1
  IFS= read -r line && [[ "$line" == 'VERSION 3' ]] || return 1
  while IFS= read -r line; do
    if [[ -z "$line" ]]; then boundary=true; break; fi
    [[ "$line" == *=* ]] || return 1
  done
  [[ "$boundary" == true ]] || return 1
  mapfile -t rows < "$stage/apt-$mode-plan.expected"
  while IFS= read -r line; do
    read -r -a columns <<< "$line"
    [[ ${#columns[@]} == 9 && "$index" -lt ${#rows[@]} ]] || return 1
    case "${columns[3]}:${columns[7]}" in *no*)
      [[ "${columns[3]}" != no ]] || columns[3]=none
      [[ "${columns[7]}" != no ]] || columns[7]=none;; esac
    expected=${rows[$index]}
    [[ "${columns[*]}" == "$expected" ]] || return 1
    index=$((index+1))
  done
  [[ "$index" == ${#rows[@]} ]] && provider_apt_status_guard "$stage" "$mode" || return
  # Only this protected marker authorizes later restoration of our own partial
  # mutation. No marker means contention/conflict, never an old-snapshot rollback.
  provider_json_write "$stage/apt-$mode-entered.json" '{"schema_version":1,"pre_mutation_guards_passed":true}'
}
provider_apt_post() {
  local stage=$1 mode=$2
  [[ -f "$stage/apt-$mode-entered.json" ]] || return 1
  provider_package_status > "$stage/apt-$mode-status.after" \
    && provider_package_selections > "$stage/apt-$mode-selections.after" \
    && sync -f "$stage/apt-$mode-status.after" && sync -f "$stage/apt-$mode-selections.after" || return
  provider_json_write "$stage/apt-$mode-post.json" "$(jq -cn \
    --arg status "$(sha256sum "$stage/apt-$mode-status.after" | cut -d ' ' -f 1)" \
    --arg selections "$(sha256sum "$stage/apt-$mode-selections.after" | cut -d ' ' -f 1)" \
    '{schema_version:1,status_sha256:$status,selections_sha256:$selections}')"
}
provider_apt_after_matches() {
  local stage=$1 mode=$2
  [[ -f "$stage/apt-$mode-post.json" \
    && $(provider_package_status | sha256sum | cut -d ' ' -f 1) == $(jq -r .status_sha256 "$stage/apt-$mode-post.json") \
    && $(provider_package_selections | sha256sum | cut -d ' ' -f 1) == $(jq -r .selections_sha256 "$stage/apt-$mode-post.json") ]]
}
provider_apt_run() {
  local stage=$1 mode=$2 result=0 hook name function
  shift 2
  [[ "$mode" == forward || "$mode" == rollback ]] || return 1
  provider_plan_expected "$stage" "$mode" || return
  for name in pre plan post; do
    case "$name" in pre) function=provider_apt_status_guard;; plan) function=provider_apt_plan_guard;; post) function=provider_apt_post;; esac
    hook="$stage/apt-$mode-$name"
    printf '#!/usr/bin/env bash\nset -euo pipefail\nsource %q\n%s %q %q\n' "$stage/transaction.sh" "$function" "$stage" "$mode" > "$hook" \
      && chmod 0700 "$hook" || return
  done
  hook="$stage/apt-$mode-plan"
  timeout --signal=TERM --kill-after=10s 180s env -u DPKG_FRONTEND_LOCKED -u APT_HOOK_INFO_FD DEBIAN_FRONTEND=noninteractive \
    apt-get -y --no-download --no-install-recommends -o Dpkg::Options::=--force-confold \
    -o "DPkg::Pre-Invoke::=$stage/apt-$mode-pre" -o "DPkg::Pre-Install-Pkgs::=$hook" \
    -o "DPkg::Tools::Options::$hook::Version=3" -o "DPkg::Tools::Options::$hook::InfoFD=0" \
    -o "DPkg::Post-Invoke::=$stage/apt-$mode-post" "$@" >&2 || result=$?
  if [[ -f "$stage/apt-$mode-entered.json" ]]; then
    if provider_apt_after_matches "$stage" "$mode"; then package_attempt_state=mutated; else package_attempt_state=uncertain; return 1; fi
  elif [[ "$result" == 0 && ! -s "$stage/apt-$mode-plan.expected" ]] \
    && [[ $(provider_package_status | sha256sum | cut -d ' ' -f 1) == $(sha256sum "$stage/apt-$mode-status.expected" | cut -d ' ' -f 1) ]]; then
    package_attempt_state=unchanged
  else package_attempt_state=conflict; return 1; fi
  return "$result"
}
provider_block_autostart() {
  rm -f -- /usr/sbin/policy-rc.d || return
  printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 0755 /usr/sbin/policy-rc.d || return
  rm -rf -- /run/systemd/system/ModemManager.service.d || return
  mkdir -p /run/systemd/system/ModemManager.service.d || return
  printf '[Unit]\nRefuseManualStart=yes\n' > /run/systemd/system/ModemManager.service.d/99-yoyopod-maintenance.conf || return
  systemctl daemon-reload
}
install_candidate() {
  local stage=$1
  package_attempt_state=conflict
  (cd -- "$stage/prior" && sha256sum -c --strict SHA256SUMS) >&2 || return
  [[ $(sha256sum /var/lib/dpkg/status | cut -d ' ' -f 1) == $(sha256sum "$stage/prior/status" | cut -d ' ' -f 1) ]] || return 1
  cp -- "$stage/prior/status" "$stage/apt-forward-status.expected" \
    && cp -- "$stage/prior/selections" "$stage/apt-forward-selections.expected" || return
  provider_block_autostart || return
  local -a packages=()
  mapfile -t packages < <(jq -r '.packages[].file' "$stage/candidate/providers/modemmanager/manifest.json" | sed "s|^|$stage/candidate/providers/modemmanager/|")
  provider_apt_run "$stage" forward install -- "${packages[@]}" || return
  install -o root -g root -m 0644 -- "$stage/udev.rules" /etc/udev/rules.d/77-yoyopod-sim7600.rules || return
  udevadm control --reload-rules && udevadm trigger --subsystem-match=tty && udevadm trigger --subsystem-match=usbmisc && udevadm settle || return
  provider_restore_temporary_policy "$stage"
}
start_provider() { timeout 30s systemctl start ModemManager.service; }

provider_current_modem() {
  local owner=$1 objects modem key property value matching matches=0 selected='' state lock primary ports emergency
  objects=$(provider_bus call "$owner" /org/freedesktop/ModemManager1 org.freedesktop.DBus.ObjectManager GetManagedObjects) || return
  while IFS= read -r modem; do
    [[ "$modem" =~ ^/org/freedesktop/ModemManager1/Modem/(0|[1-9][0-9]*)$ ]] || continue
    matching=true
    for key in manufacturer model revision hardware_revision plugin; do
      case "$key" in manufacturer) property=Manufacturer;; model) property=Model;; revision) property=Revision;; hardware_revision) property=HardwareRevision;; plugin) property=Plugin;; esac
      value=$(provider_bus get-property "$owner" "$modem" org.freedesktop.ModemManager1.Modem "$property" | jq -er '.data[0]') || return
      [[ "$value" == $(jq -r --arg key "$key" '.modem[$key]' "$provider_stage/candidate/providers/modemmanager/profile.json") ]] || matching=false
    done
    if "$matching"; then selected=$modem; matches=$((matches+1)); fi
  done < <(jq -r '.data[0]|keys[]' <<< "$objects")
  [[ "$matches" == 1 ]] || return 1
  state=$(provider_bus get-property "$owner" "$selected" org.freedesktop.ModemManager1.Modem State | jq -er '.data[0]') || return
  lock=$(provider_bus get-property "$owner" "$selected" org.freedesktop.ModemManager1.Modem UnlockRequired | jq -er '.data[0]') || return
  [[ "$state" =~ ^[0-9]+$ && "$state" -ge 6 && "$lock" =~ ^(1|3|5)$ ]] || return 1
  emergency=$(provider_bus get-property "$owner" "$selected" org.freedesktop.ModemManager1.Modem.Voice EmergencyOnly | jq -er '.data==[false]') || return
  primary=$(provider_bus get-property "$owner" "$selected" org.freedesktop.ModemManager1.Modem PrimaryPort | jq -er '.data[0]') || return
  ports=$(provider_bus get-property "$owner" "$selected" org.freedesktop.ModemManager1.Modem Ports) || return
  jq -e --arg primary "$primary" '.data[0]|any(.[];.[0]==$primary and .[1]==6)' <<< "$ports" >/dev/null || return
  printf '%s\n' "$selected"
}
provider_latest_init() {
  journalctl --no-pager -o json "_SYSTEMD_INVOCATION_ID=$2" "_PID=$1" \
    | jq -r --arg tag "[modem${3##*/}]" 'select((.MESSAGE|contains($tag)) and (.MESSAGE|contains("voice-audio contract=1 ")))|.MESSAGE' | tail -n 1
}
provider_verify_restored_init() {
  local stage=$1 identity=$2 owner pid invocation modem latest='' attempt ready=false version
  owner=$(jq -r .unique_owner <<< "$identity"); pid=$(jq -r .pid <<< "$identity")
  version=$(jq -r .package_version <<< "$identity") || return
  [[ "$owner" != $(jq -r .unique_owner "$stage/prior/identity.json") ]] || return 1
  invocation=$(systemctl show -p InvocationID --value ModemManager.service) || return
  [[ "$invocation" =~ ^[0-9a-f]{32}$ && "$invocation" != $(cat "$stage/prior/provider-invocation") ]] || return 1
  for attempt in $(seq 1 30); do
    # State >= ENABLED, lock/emergency status, exact hardware/firmware/plugin and
    # current QMI inventory are affirmative normal initialization health, even
    # for stock. Voice export/empty Calls alone never reaches this boundary.
    modem=$(provider_current_modem "$owner") || { sleep 1; continue; }
    if [[ "$version" == *+yoyopod1 ]]; then
      [[ -f "$stage/prior/files/var/lib/yoyopod/providers/modemmanager/manifest.json" \
        && $(jq -r .daemon_sha256 "$stage/prior/files/var/lib/yoyopod/providers/modemmanager/manifest.json") == $(jq -r .running_daemon_sha256 <<< "$identity") ]] || return 1
      latest=$(provider_latest_init "$pid" "$invocation" "$modem") || return
      if [[ "$latest" =~ voice-audio\ contract=1\ generation=[0-9]+\ operation=[0-9]+\ selection=ok\ readback=ok$ ]]; then ready=true; break; fi
      [[ -z "$latest" ]] || return 1
    else ready=true; break; fi
    sleep 1
  done
  [[ "$ready" == true && $(provider_identity) == "$identity" \
    && $(systemctl show -p InvocationID --value ModemManager.service) == "$invocation" ]] \
    && provider_no_calls "$owner"
}
provider_attest() {
  local stage=$1 expected=$2 identity again manifest receipt_dir=/var/lib/yoyopod/providers/modemmanager receipt temporary_manifest temporary_profile temporary_receipt
  identity=$(provider_identity) || return
  [[ $(jq -r .running_daemon_sha256 <<< "$identity") == "$expected" \
    && $(jq -r .package_version <<< "$identity") == $(jq -r .package_version "$stage/candidate/providers/modemmanager/manifest.json") \
    && $(jq -r .architecture <<< "$identity") == arm64 ]] || return 1
  provider_no_calls "$(jq -r .unique_owner <<< "$identity")" || return
  again=$(provider_identity) || return
  [[ "$identity" == "$again" ]] || return 1
  manifest="$stage/candidate/providers/modemmanager"
  receipt=$(jq -cn --arg manifest "$(sha256sum "$manifest/manifest.json" | cut -d ' ' -f 1)" \
    --arg profile "$(sha256sum "$manifest/profile.json" | cut -d ' ' -f 1)" --argjson identity "$identity" \
    '{schema_version:1,manifest:"manifest.json",profile:"profile.json",manifest_sha256:$manifest,profile_sha256:$profile,running_identity:$identity}') || return
  provider_protected_directory "$receipt_dir" || return
  for file in installed.json manifest.json profile.json; do [[ ! -L "$receipt_dir/$file" ]] || return 1; done
  temporary_manifest=$(mktemp "$receipt_dir/.manifest.XXXXXXXXXXXX") || return
  temporary_profile=$(mktemp "$receipt_dir/.profile.XXXXXXXXXXXX") || return
  temporary_receipt=$(mktemp "$receipt_dir/.installed.XXXXXXXXXXXX") || return
  install -o root -g root -m 0644 -- "$manifest/manifest.json" "$temporary_manifest" \
    && install -o root -g root -m 0644 -- "$manifest/profile.json" "$temporary_profile" || return
  printf '%s\n' "$receipt" > "$temporary_receipt" && chmod 0644 "$temporary_receipt" || return
  sync -f "$temporary_manifest" && sync -f "$temporary_profile" && sync -f "$temporary_receipt" || return
  mv -f -- "$temporary_manifest" "$receipt_dir/manifest.json" && mv -f -- "$temporary_profile" "$receipt_dir/profile.json" \
    && mv -f -- "$temporary_receipt" "$receipt_dir/installed.json" && sync -f "$receipt_dir" || return
  [[ $(provider_identity) == "$identity" ]] || return 1
  current_identity=$identity
}
verify_provider_init() {
  local stage=$1 identity owner pid invocation modem latest expected attempt
  for attempt in $(seq 1 30); do identity=$(provider_identity) && break; sleep 1; done
  [[ -n "${identity:-}" && "$identity" != "$before_identity" ]] || return 1
  owner=$(jq -r .unique_owner <<< "$identity"); pid=$(jq -r .pid <<< "$identity")
  [[ "$owner" != $(jq -r .unique_owner <<< "$before_identity") ]] || return 1
  invocation=$(systemctl show -p InvocationID --value ModemManager.service) || return
  [[ "$invocation" =~ ^[0-9a-f]{32}$ ]] || return 1
  for attempt in $(seq 1 30); do
    modem=$(provider_current_modem "$owner") || { sleep 1; continue; }
    latest=$(provider_latest_init "$pid" "$invocation" "$modem") || return
    [[ "$latest" == *' selection=ok readback=ok' ]] && break
    [[ -z "$latest" ]] || return 1
    sleep 1
  done
  [[ "${latest:-}" =~ voice-audio\ contract=1\ generation=[0-9]+\ operation=[0-9]+\ selection=ok\ readback=ok$ ]] || return 1
  [[ $(provider_identity) == "$identity" ]] || return 1
  expected=$(jq -er .daemon_sha256 "$stage/candidate/providers/modemmanager/manifest.json") || return
  current_provider_invocation=$invocation
  provider_attest "$stage" "$expected"
}
provider_copy_rust() {
  local stage=$1 root=$2 file destination mode
  while IFS= read -r file; do
    destination="$checkout/$file"
    runuser -u "$service_user" -- mkdir -p -- "$(dirname -- "$destination")" || return
    mode=755
    if [[ "${restoring:-false}" == true ]]; then mode=$(stat -c %a "$root/$file") || return; fi
    cat "$root/$file" | runuser -u "$service_user" -- bash -c 'set -e; if test -e "$1"; then chmod u+w -- "$1"; fi; cat > "$1"; chmod "$2" -- "$1"' -- "$destination" "$mode" || return
    [[ $(sha256sum "$root/$file" | cut -d ' ' -f 1) == $(sha256sum "$destination" | cut -d ' ' -f 1) ]] || return 1
  done < <(jq -r '.binaries[].file' "$stage/candidate/manifest.json")
}
start_native() {
  local dev=$1 sha
  if [[ "${restoring:-false}" != true ]]; then
    sha=$(jq -er .repo_sha "$provider_stage/control.json") || return
    runuser -u "$service_user" -- git -C "$checkout" fetch --no-tags "$provider_stage/repository.git" "$sha" >&2 \
      && runuser -u "$service_user" -- git -C "$checkout" checkout --detach --force "$sha" >&2 || return
    provider_copy_rust "$provider_stage" "$provider_stage/candidate" || return
  fi
  timeout 30s systemctl start "$dev"
}
provider_network_identity() {
  local expected=$1 executable process group parent ticks pid='' actual
  group=$(systemctl show -p ControlGroup --value "$dev_service") || return
  parent=$(systemctl show -p MainPID --value "$dev_service") || return
  [[ "$parent" =~ ^[1-9][0-9]*$ && -n "$group" ]] || return 1
  for process in /proc/[0-9]*; do
    if executable=$(provider_process_executable "$process"); then :; else [[ $? == 1 ]] && continue; return 1; fi
    [[ "${executable##*/}" == yoyopod-network-host ]] || continue
    [[ -z "$pid" ]] || return 1
    grep -Fxq "0::$group" "$process/cgroup" || return
    [[ $(awk '/^PPid:/{print $2}' "$process/status") == "$parent" ]] || return 1
    pid=${process##*/}
  done
  [[ -n "$pid" ]] || return 1
  ticks=$(provider_ticks "$pid") || return
  actual=$(sha256sum "/proc/$pid/exe" | cut -d ' ' -f 1) || return
  [[ "$actual" == "$expected" && $(provider_ticks "$pid") == "$ticks" ]] || return 1
  jq -cn --argjson pid "$pid" --argjson ticks "$ticks" --arg hash "$actual" '{pid:$pid,process_start_ticks:$ticks,sha256:$hash}'
}
provider_latest_result() {
  local pid=$1 ticks=$2 hz=$3
  jq -r --arg suffix " pid=$pid" --argjson ticks "$ticks" --argjson hz "$hz" \
    'select((.__MONOTONIC_TIMESTAMP|tonumber)>=($ticks*1000000/$hz) and
      (.MESSAGE|startswith("GSM provider audio unavailable: ")) and (.MESSAGE|endswith($suffix)))|.MESSAGE' | tail -n 1
}
provider_pending_result() {
  [[ $(provider_latest_result "$1" "$2" "$3") == "GSM provider audio unavailable: GSM provider installed, qualification pending pid=$1" ]]
}
verify_native_expected() {
  local stage=$1 identity again receipt=/var/lib/yoyopod/providers/modemmanager/installed.json qualification invocation worker expected pid ticks hz latest logs file mode attempt
  runuser -u "$service_user" -- bash -s < "$stage/native-verify.sh" >&2 || return
  if [[ "${restoring:-false}" == true ]]; then
    expected=$(sha256sum "$stage/prior/rust/device/network/build/yoyopod-network-host" | cut -d ' ' -f 1) || return
    provider_network_identity "$expected" >/dev/null
    return $?
  fi
  identity=$(provider_identity) || return
  [[ "$identity" == "$current_identity" ]] || return 1
  provider_protected_directory /var/lib/yoyopod/providers/modemmanager || return
  for file in installed.json manifest.json profile.json; do
    [[ ! -L "/var/lib/yoyopod/providers/modemmanager/$file" && $(stat -c %u "/var/lib/yoyopod/providers/modemmanager/$file") == 0 ]] || return 1
    mode=$(stat -c %a "/var/lib/yoyopod/providers/modemmanager/$file") || return
    (( (8#$mode & 0022) == 0 )) || return 1
    runuser -u "$service_user" -- cat "/var/lib/yoyopod/providers/modemmanager/$file" >/dev/null || return
  done
  runuser -u "$service_user" -- cat "/proc/$(jq -r .pid <<< "$identity")/stat" >/dev/null || return
  [[ $(runuser -u "$service_user" -- sha256sum /usr/sbin/ModemManager | cut -d ' ' -f 1) == $(jq -r .installed_executable_sha256 <<< "$identity") ]] || return 1
  [[ $(runuser -u "$service_user" -- timeout 10s busctl --system --json=short call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus GetNameOwner s org.freedesktop.ModemManager1 | jq -er '.data[0]') == $(jq -r .unique_owner <<< "$identity") ]] || return 1
  jq -e --argjson identity "$identity" '.running_identity==$identity' "$receipt" >/dev/null || return
  [[ $(sha256sum /var/lib/yoyopod/providers/modemmanager/manifest.json | cut -d ' ' -f 1) == $(jq -r .manifest_sha256 "$receipt") \
    && $(sha256sum /var/lib/yoyopod/providers/modemmanager/profile.json | cut -d ' ' -f 1) == $(jq -r .profile_sha256 "$receipt") ]] || return 1
  expected=$(jq -er '.binaries[]|select(.file=="device/network/build/yoyopod-network-host")|.sha256' "$stage/candidate/manifest.json") || return
  worker=$(provider_network_identity "$expected") || return
  pid=$(jq -r .pid <<< "$worker"); ticks=$(jq -r .process_start_ticks <<< "$worker")
  hz=$(getconf CLK_TCK) || return
  invocation=$(systemctl show -p InvocationID --value "$dev_service") || return
  [[ "$invocation" =~ ^[0-9a-f]{32}$ ]] || return 1
  qualification=$(jq -er .qualification "$stage/candidate/providers/modemmanager/profile.json") || return
  for attempt in $(seq 1 20); do
    logs=$(journalctl --no-pager -o json "_SYSTEMD_INVOCATION_ID=$invocation" \
      | jq -c --argjson ticks "$ticks" --argjson hz "$hz" 'select((.__MONOTONIC_TIMESTAMP|tonumber)>=($ticks*1000000/$hz))') || return
    latest=$(jq -r --arg prefix "GSM availability pid=$pid available=" 'select(.MESSAGE|contains($prefix))|.MESSAGE' <<< "$logs" | tail -n 1) || return
    if [[ "$qualification" == qualification_pending ]]; then
      if [[ "$latest" == "GSM availability pid=$pid available=false" ]] \
        && provider_pending_result "$pid" "$ticks" "$hz" <<< "$logs"; then
        outcome=installed_qualification_pending; break
      fi
    elif [[ "$qualification" == qualified && "$latest" == "GSM availability pid=$pid available=true" ]]; then outcome=qualified_ready; break
    fi
    sleep 1
  done
  [[ -n "${outcome:-}" && $(provider_network_identity "$expected") == "$worker" && $(provider_identity) == "$identity" \
    && $(systemctl show -p InvocationID --value "$dev_service") == "$invocation" ]] || return 1
  file=$(provider_current_modem "$(jq -r .unique_owner <<< "$identity")") || return
  [[ $(systemctl show -p InvocationID --value ModemManager.service) == "$current_provider_invocation" \
    && $(provider_latest_init "$(jq -r .pid <<< "$identity")" "$current_provider_invocation" "$file") =~ voice-audio\ contract=1\ generation=[0-9]+\ operation=[0-9]+\ selection=ok\ readback=ok$ ]] || return 1
  latest=$(journalctl --no-pager -o json "_SYSTEMD_INVOCATION_ID=$invocation" \
    | jq -r --argjson ticks "$ticks" --argjson hz "$hz" --arg prefix "GSM availability pid=$pid available=" \
      'select((.__MONOTONIC_TIMESTAMP|tonumber)>=($ticks*1000000/$hz) and (.MESSAGE|contains($prefix)))|.MESSAGE' | tail -n 1) || return
  if [[ "$outcome" == qualified_ready ]]; then [[ "$latest" == "GSM availability pid=$pid available=true" ]] || return 1
  else
    [[ "$latest" == "GSM availability pid=$pid available=false" ]] || return 1
    journalctl --no-pager -o json "_SYSTEMD_INVOCATION_ID=$invocation" \
      | provider_pending_result "$pid" "$ticks" "$hz" || return
  fi
  [[ $(provider_network_identity "$expected") == "$worker" && $(provider_identity) == "$identity" ]]
}

restore_prior_packages() {
  local stage=$1 name version architecture
  (cd -- "$stage/prior" && sha256sum -c --strict SHA256SUMS) >&2 || return
  if [[ "$package_attempt_state" == mutated ]]; then
    provider_apt_after_matches "$stage" forward || return
    cp -- "$stage/apt-forward-status.after" "$stage/apt-rollback-status.expected" \
      && cp -- "$stage/apt-forward-selections.after" "$stage/apt-rollback-selections.expected" || return
  elif [[ "$package_attempt_state" == unchanged ]]; then
    cp -- "$stage/prior/status" "$stage/apt-rollback-status.expected" \
      && cp -- "$stage/prior/selections" "$stage/apt-rollback-selections.expected" || return
  else return 1; fi
  provider_block_autostart || return
  local -a packages=() removals=()
  mapfile -t packages < <(find "$stage/prior/packages" -type f -name '*.deb' -print | LC_ALL=C sort)
  while IFS= read -r name; do removals+=("$name-"); done < "$stage/prior/additions"
  provider_simulation "$stage" rollback /var/lib/dpkg/status || return
  provider_apt_run "$stage" rollback --allow-downgrades --purge install -- "${packages[@]}" "${removals[@]}" || return
  while IFS=$'\t' read -r name version architecture; do
    [[ $(dpkg-query -W -f='${Version}\t${Architecture}' "$name") == "$version"$'\t'"$architecture" \
      && $(dpkg-query -W -f='${db:Status-Status}' "$name") == installed ]] || return 1
  done < "$stage/prior/installed.tsv"
  while IFS= read -r name; do
    [[ $(dpkg-query -W -f='${db:Status-Status}' "$name" 2>/dev/null) != installed ]] || return 1
  done < "$stage/prior/additions"
  [[ -z $(dpkg --audit) ]]
}
restore_prior_service() {
  local stage=$1 path prior identity expected receipt temporary ready=false attempt
  while IFS= read -r path; do
    [[ "$path" == /etc/* || "$path" == /run/systemd/system/ModemManager.service.d \
      || "$path" == /usr/sbin/policy-rc.d || "$path" == /var/lib/yoyopod/providers/modemmanager/*.json ]] || return 1
    [[ "$path" != *'/../'* && "$path" != *'/./'* && "$path" != *'//'*
      && "$path" != *$'\n'* && "$path" != *$'\r'* ]] || return 1
    rm -rf -- "$path" || return
    prior="$stage/prior/files$path"
    if [[ -e "$prior" || -L "$prior" ]]; then mkdir -p -- "$(dirname -- "$path")" && cp -a -- "$prior" "$path" || return; fi
  done < "$stage/prior/paths"
  systemctl daemon-reload && provider_restore_enabled "$stage" && udevadm control --reload-rules \
    && udevadm trigger --subsystem-match=tty && udevadm trigger --subsystem-match=usbmisc && udevadm settle && provider_start_provider || return
  expected=$(jq -r .running_daemon_sha256 "$stage/prior/identity.json") || return
  for attempt in $(seq 1 30); do
    if identity=$(provider_identity) \
      && [[ $(jq -r .running_daemon_sha256 <<< "$identity") == "$expected" \
        && $(jq -r .package_version <<< "$identity") == $(jq -r .package_version "$stage/prior/identity.json") \
        && $(jq -r .architecture <<< "$identity") == $(jq -r .architecture "$stage/prior/identity.json") ]] \
      && provider_no_calls "$(jq -r .unique_owner <<< "$identity")"; then ready=true; break; fi
    sleep 1
  done
  [[ "$ready" == true ]] || return 1
  provider_verify_restored_init "$stage" "$identity" || return
  receipt=/var/lib/yoyopod/providers/modemmanager/installed.json
  if [[ -f "$receipt" ]]; then
    # A new restored process needs maintenance reattestation. All copied prior
    # manifest/profile bytes remain exact; only this new process identity changes.
    prior=$(jq --argjson identity "$identity" '.running_identity=$identity' "$receipt") || return
    temporary=$(mktemp /var/lib/yoyopod/providers/modemmanager/.restore.XXXXXXXXXXXX) || return
    printf '%s\n' "$prior" > "$temporary" && chmod 0644 "$temporary" && sync -f "$temporary" \
      && mv -f -- "$temporary" "$receipt" && sync -f "$(dirname -- "$receipt")" || return
  fi
  [[ $(provider_identity) == "$identity" ]]
}
restore_prior_rust() {
  local stage=$1 sha branch
  sha=$(cat "$stage/prior/repo-sha") || return
  branch=$(cat "$stage/prior/branch") || return
  if [[ -n "$branch" ]]; then runuser -u "$service_user" -- git -C "$checkout" checkout --force "$branch" >&2 || return
  else runuser -u "$service_user" -- git -C "$checkout" checkout --detach --force "$sha" >&2 || return; fi
  runuser -u "$service_user" -- git -C "$checkout" reset --hard "$sha" >&2 || return
  provider_copy_rust "$stage" "$stage/prior/rust" || return
  provider_restore_config "$stage" || return
  provider_restore_rust_metadata "$stage" || return
  provider_config_restorable "$checkout/config" "$service_user" || return
  [[ $(runuser -u "$service_user" -- git -C "$checkout" rev-parse HEAD) == "$sha" ]]
}
provider_restore_config() {
  local stage=$1
  runuser -u "$service_user" -- rm -rf -- "$checkout/config" || return
  runuser -u "$service_user" -- mkdir -p -- "$checkout/config" || return
  tar -C "$stage/prior/config" -cf - . \
    | runuser -u "$service_user" -- tar --same-owner --same-permissions -C "$checkout/config" -xf - || return
  provider_config_metadata "$checkout/config" > "$stage/config-metadata.restored" || return
  cmp -s -- "$stage/prior/config-metadata" "$stage/config-metadata.restored"
}
provider_restore_rust_metadata() {
  local stage=$1 path mode target
  while IFS=$'\t' read -r path mode; do
    if [[ "$path" == . ]]; then target=$checkout
    else
      [[ "$path" == /device/* || "$path" == /device ]] || return 1
      target="$checkout$path"
    fi
    runuser -u "$service_user" -- chmod "$mode" -- "$target" || return
    provider_metadata_supported "$target" "$service_user" || return
    [[ $(stat -c %a "$target") == "$mode" ]] || return 1
  done < "$stage/prior/rust-metadata"
}
provider_recovery_stop() {
  local stage=$1 dev=$2
  native_stopped=false; provider_stopped=false
  if stop_native "$dev"; then native_stopped=true; fi
  if stop_provider "$(provider_stop_identity)"; then provider_stopped=true; fi
  write_recovery_record "$stage" || return 2
  return 2
}
provider_rollback() {
  local stage=$1 dev=$2
  restoring=true
  provider_phase "$stage" rollback || { provider_recovery_stop "$stage" "$dev"; return 2; }
  native_stopped=false; provider_stopped=false
  if stop_native "$dev"; then native_stopped=true; fi
  if stop_provider "$(provider_stop_identity)"; then provider_stopped=true; fi
  if [[ "$native_stopped" != true || "$provider_stopped" != true ]]; then write_recovery_record "$stage"; return 2; fi
  if [[ "$package_attempt_state" != mutated && "$package_attempt_state" != unchanged ]]; then
    failure_reason='APT conflict or missing protected post-attempt evidence; prior snapshot must not overwrite external changes'
    provider_restore_temporary_policy "$stage" || :
    write_recovery_record "$stage"; return 2
  fi
  if restore_prior_packages "$stage" && restore_prior_service "$stage" && restore_prior_rust "$stage" \
    && provider_start_native "$dev" && verify_native_expected "$stage"; then
    provider_json_write "$stage/outcome.json" '{"schema_version":1,"outcome":"rolled_back"}' \
      || { provider_recovery_stop "$stage" "$dev"; return 2; }
    return 1
  fi
  provider_recovery_stop "$stage" "$dev"
}
provider_main() (
  set -u
  local provider_stage=$1 dev_service=$2 prod_service=$3 phase=preflight failure_reason='transaction failed'
  local native_stopped=false provider_stopped=false prior_ready=false restoring=false
  local before_identity='' current_identity='' current_provider_invocation='' service_user='' checkout='' outcome='' before_modem=''
  local started_identity='' provider_start_attempted=false
  local package_attempt_state=not_attempted
  verify_stage "$provider_stage" && require_dev_no_calls "$dev_service" "$prod_service" || return 1
  provider_phase "$provider_stage" capturing || return 1
  trap 'failure_reason="interrupted"; trap - INT TERM HUP; if [[ "$prior_ready" == true ]]; then provider_rollback "$provider_stage" "$dev_service"; else write_recovery_record "$provider_stage"; fi; exit 2' INT TERM HUP
  capture_prior "$provider_stage" || return 1
  provider_phase "$provider_stage" staged || return 1
  provider_pre_stop || return 1
  provider_phase "$provider_stage" stopping || return 1
  if stop_native "$dev_service"; then native_stopped=true; else
    failure_reason='native stop not proven'; write_recovery_record "$provider_stage"; return 2
  fi
  if ! provider_pre_stop; then
    failure_reason='provider owner/call proof changed after native stop'; write_recovery_record "$provider_stage"; return 2
  fi
  if stop_provider "$before_identity"; then provider_stopped=true; else
    failure_reason='provider stop not proven'; write_recovery_record "$provider_stage"; return 2
  fi
  provider_phase "$provider_stage" installing || { provider_recovery_stop "$provider_stage" "$dev_service"; return 2; }
  if install_candidate "$provider_stage" && provider_start_provider && verify_provider_init "$provider_stage" \
    && provider_start_native "$dev_service" && verify_native_expected "$provider_stage"; then
    provider_phase "$provider_stage" installed || { provider_recovery_stop "$provider_stage" "$dev_service"; return 2; }
    provider_json_write "$provider_stage/outcome.json" "$(jq -cn --arg outcome "$outcome" '{schema_version:1,outcome:$outcome}')" \
      || { provider_recovery_stop "$provider_stage" "$dev_service"; return 2; }
    trap - INT TERM HUP
    cat "$provider_stage/outcome.json"
    return 0
  fi
  provider_rollback "$provider_stage" "$dev_service"
)
provider_entry() (
  set -euo pipefail
  umask 077
  [[ $# == 3 && $(id -u) == 0 && ${YOYOPOD_STAGE_INPUTS_SHA256:-} =~ ^[0-9a-f]{64}$ ]] || exit 2
  local upload=$1 dev=$2 prod=$3 expected_inputs=$YOYOPOD_STAGE_INPUTS_SHA256 root=/var/lib/yoyopod/providers/modemmanager sha stage directory
  [[ "$upload" =~ ^/tmp/yoyopod-provider\.[a-zA-Z0-9]+$ && -d "$upload" && ! -L "$upload" ]] || exit 2
  [[ "$dev" =~ ^[a-zA-Z0-9_.@-]+\.service$ && "$prod" =~ ^[a-zA-Z0-9_.@-]+\.service$ ]] || exit 2
  [[ -f "$upload/inputs.sha256" && ! -L "$upload/inputs.sha256" \
    && $(sha256sum "$upload/inputs.sha256" | cut -d ' ' -f 1) == "$expected_inputs" ]] || exit 1
  provider_migrate_common_parent "$dev"
  for directory in /var/lib/yoyopod /var/lib/yoyopod/providers "$root" "$root/transactions"; do
    provider_protected_directory "$(dirname -- "$directory")"
    if [[ ! -e "$directory" && ! -L "$directory" ]]; then install -d -o root -g root -m 0755 "$directory"; fi
    provider_protected_directory "$directory"
  done
  [[ ! -L "$root/maintenance.lock" ]] || exit 1
  exec 9>"$root/maintenance.lock"
  flock -n 9
  [[ -f "$upload/inputs.sha256" && ! -L "$upload/inputs.sha256" \
    && $(sha256sum "$upload/inputs.sha256" | cut -d ' ' -f 1) == "$expected_inputs" ]] || exit 1
  sha=$(jq -er '.repo_sha|select(test("^[0-9a-f]{40}$"))' "$upload/control.json")
  if [[ ! -e "$root/transactions/$sha" && ! -L "$root/transactions/$sha" ]]; then install -d -o root -g root -m 0755 "$root/transactions/$sha"; fi
  provider_protected_directory "$root/transactions/$sha"
  stage=$(mktemp -d "$root/transactions/$sha/attempt.XXXXXXXXXXXX")
  cp -R --no-dereference --no-preserve=ownership,mode -- "$upload/." "$stage/"
  [[ -z $(find -P "$stage" -mindepth 1 ! -type f ! -type d -print -quit) ]] || exit 1
  find "$stage" -type d -exec chmod 0755 {} +
  find "$stage" -type f -exec chmod 0644 {} +
  echo "provider transaction stage: $stage" >&2
  provider_main "$stage" "$dev" "$prod"
)
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then provider_entry "$@"; fi
