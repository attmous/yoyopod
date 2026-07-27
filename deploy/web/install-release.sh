#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="/opt/yoyopod-web"
RELEASES_DIR="${APP_ROOT}/releases"
CURRENT_LINK="${APP_ROOT}/current"
PREVIOUS_LINK="${APP_ROOT}/previous"
DEPLOYED_SHA_FILE="${APP_ROOT}/DEPLOYED_SHA"
EXPECTED_USER="yoyopod-web-deploy"
NGINX_CONFIG="/etc/nginx/sites-available/yoyopod"
MAX_RELEASE_HISTORY=5
MAX_RELEASE_BYTES=$((256 * 1024 * 1024))
MAX_RELEASE_ENTRIES=10000

usage() {
    echo "usage: install-release.sh ARCHIVE RELEASE_ID COMMIT_SHA" >&2
    exit 2
}

[[ "$#" -eq 3 ]] || usage

ARCHIVE="$1"
RELEASE_ID="$2"
COMMIT_SHA="$3"

if [[ "$(id -un)" != "${EXPECTED_USER}" ]]; then
    echo "install-release.sh must run as ${EXPECTED_USER}" >&2
    exit 1
fi
# Privilege transitions from root commonly inherit /root as the working
# directory. Enter a world-readable directory before GNU find/tar attempt to
# save and restore cwd.
cd /

if [[ ! "${RELEASE_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{7,79}$ ]]; then
    echo "invalid release id: ${RELEASE_ID}" >&2
    exit 1
fi
if [[ ! "${COMMIT_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "commit SHA must be 40 lowercase hexadecimal characters" >&2
    exit 1
fi
if [[ ! -f "${ARCHIVE}" ]]; then
    echo "release archive does not exist: ${ARCHIVE}" >&2
    exit 1
fi
if [[ ! -d "${RELEASES_DIR}" || ! -w "${RELEASES_DIR}" ]]; then
    echo "release root is not writable; run deploy/web/bootstrap-vps.sh first" >&2
    exit 1
fi

# Serialize every installer, including the manual PowerShell path and GitHub
# Actions. The workflow concurrency group alone cannot protect the VPS from a
# manual deploy that overlaps a CI run.
exec 9> "${APP_ROOT}/.deploy.lock"
if ! flock --wait 300 9; then
    echo "timed out waiting for the web deployment lock" >&2
    exit 1
fi

release_dir="${RELEASES_DIR}/${RELEASE_ID}"
if [[ -e "${release_dir}" ]]; then
    echo "release already exists: ${release_dir}" >&2
    exit 1
fi

archive_entry_is_safe() {
    local entry="${1#./}"
    [[ -n "${entry}" ]] || return 1
    [[ "${entry}" != /* ]] || return 1
    [[ "${entry}" != ".." && "${entry}" != ../* && "${entry}" != */../* && "${entry}" != */.. ]] || return 1
    case "${entry}" in
        root|root/*|docs|docs/*|notify-collector.mjs|REVISION)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

while IFS= read -r archive_entry; do
    if ! archive_entry_is_safe "${archive_entry}"; then
        echo "unsafe or unexpected archive entry: ${archive_entry}" >&2
        exit 1
    fi
done < <(tar -tzf "${ARCHIVE}")

archive_verbose_listing="$(
    LC_ALL=C tar --numeric-owner -tvzf "${ARCHIVE}"
)"
while IFS= read -r archive_listing; do
    entry_type="${archive_listing:0:1}"
    if [[ "${entry_type}" != "-" && "${entry_type}" != "d" ]]; then
        echo "release archives may contain only regular files and directories" >&2
        exit 1
    fi
done <<< "${archive_verbose_listing}"

read -r archive_entry_count archive_expanded_bytes < <(
    awk '
        {
            if ($3 !~ /^[0-9]+$/) {
                invalid = 1
            }
            entries += 1
            bytes += $3
        }
        END {
            if (invalid) {
                print "invalid invalid"
            } else {
                printf "%.0f %.0f\n", entries, bytes
            }
        }
    ' <<< "${archive_verbose_listing}"
)
if [[ ! "${archive_entry_count}" =~ ^[0-9]+$ ||
      ! "${archive_expanded_bytes}" =~ ^[0-9]+$ ]]; then
    echo "could not determine release archive size" >&2
    exit 1
fi
if (( archive_entry_count > MAX_RELEASE_ENTRIES )); then
    echo "release has ${archive_entry_count} entries; limit is ${MAX_RELEASE_ENTRIES}" >&2
    exit 1
fi
if (( archive_expanded_bytes > MAX_RELEASE_BYTES )); then
    echo "release expands to ${archive_expanded_bytes} bytes; limit is ${MAX_RELEASE_BYTES}" >&2
    exit 1
fi

cleanup_uninstalled_release() {
    local status="$?"
    trap - ERR
    rm -rf -- "${release_dir}"
    exit "${status}"
}
trap cleanup_uninstalled_release ERR

mkdir -m 0755 "${release_dir}"
tar \
    --extract \
    --gzip \
    --file "${ARCHIVE}" \
    --directory "${release_dir}" \
    --no-same-owner \
    --no-same-permissions

if [[ ! -f "${release_dir}/root/index.html" ||
      ! -f "${release_dir}/docs/index.html" ||
      ! -f "${release_dir}/notify-collector.mjs" ||
      ! -f "${release_dir}/REVISION" ]]; then
    echo "release is missing a required file" >&2
    exit 1
fi
if [[ "$(tr -d '\r\n' < "${release_dir}/REVISION")" != "${COMMIT_SHA}" ]]; then
    echo "archive revision does not match requested commit SHA" >&2
    exit 1
fi
if find "${release_dir}" -type l -print -quit | grep -q .; then
    echo "release archives may not contain symbolic links" >&2
    exit 1
fi

find "${release_dir}" -type d -exec chmod 0755 {} +
find "${release_dir}" -type f -exec chmod 0644 {} +
trap - ERR

old_target="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
switched=0

switch_current_to() {
    local target="$1"
    local relative_target
    relative_target="releases/$(basename -- "${target}")"
    local temporary_link="${APP_ROOT}/.current-${RELEASE_ID}-$$"
    ln -s "${relative_target}" "${temporary_link}"
    mv -Tf "${temporary_link}" "${CURRENT_LINK}"
}

restart_notify_if_enabled() {
    if /usr/bin/systemctl is-enabled --quiet yoyopod-notify.service; then
        sudo -n /usr/bin/systemctl restart yoyopod-notify.service
    fi
}

rollback_on_error() {
    local status="$?"
    trap - ERR
    set +e
    if [[ "${switched}" -eq 1 ]]; then
        echo "deployment verification failed; restoring the previous release" >&2
        if [[ -n "${old_target}" && "${old_target}" == "${RELEASES_DIR}/"* && -d "${old_target}" ]]; then
            switch_current_to "${old_target}"
            restart_notify_if_enabled
        else
            rm -f -- "${CURRENT_LINK}"
            restart_notify_if_enabled
        fi
        rm -rf -- "${release_dir}"
    fi
    exit "${status}"
}
trap rollback_on_error ERR

switch_current_to "${release_dir}"
switched=1
restart_notify_if_enabled

assert_status() {
    local host="$1"
    local path="$2"
    local expected="$3"
    local actual
    actual="$(
        curl \
            --silent \
            --show-error \
            --output /dev/null \
            --write-out '%{http_code}' \
            --connect-timeout 3 \
            --max-time 15 \
            --noproxy '*' \
            --resolve "${host}:${origin_port}:127.0.0.1" \
            "${origin_scheme}://${host}${path}"
    )"
    if [[ "${actual}" != "${expected}" ]]; then
        echo "${host}${path}: expected HTTP ${expected}, received ${actual}" >&2
        return 1
    fi
}

assert_status_eventually() {
    local host="$1"
    local path="$2"
    local expected="$3"
    local attempts="$4"
    local attempt
    for (( attempt = 1; attempt <= attempts; attempt += 1 )); do
        if assert_status "${host}" "${path}" "${expected}"; then
            return 0
        fi
        if (( attempt < attempts )); then
            sleep 1
        fi
    done
    return 1
}

# Certbot edits this vhost in place. Once certificate directives are present,
# probe the local HTTPS listener directly with correct SNI and certificate
# validation; otherwise use the initial HTTP listener. Public DNS is never
# involved in either path.
origin_scheme="http"
origin_port="80"
if [[ -r "${NGINX_CONFIG}" ]] &&
   grep -qiE '^[[:space:]]*ssl_certificate[[:space:]]' "${NGINX_CONFIG}"; then
    origin_scheme="https"
    origin_port="443"
fi

assert_status "yoyopod.com" "/" "200"
assert_status "yoyopod.com" "/imprint/" "200"
assert_status "docs.yoyopod.com" "/" "200"
assert_status "docs.yoyopod.com" "/this-page-does-not-exist/" "404"

# The active nginx mode is independent of release history. A closed endpoint
# must return 404. Once the reviewed loopback proxy is enabled, a safe GET
# must reach the collector's method-not-allowed response; no address is sent.
notify_expected="404"
if grep -qE \
    '^[[:space:]]*proxy_pass[[:space:]]+http://127\.0\.0\.1:8787/?;' \
    "${NGINX_CONFIG}"; then
    notify_expected="405"
fi
if [[ "${notify_expected}" == "405" ]]; then
    assert_status_eventually "yoyopod.com" "/api/notify" "405" "15"
else
    assert_status "yoyopod.com" "/api/notify" "404"
fi

if [[ "$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)" != "${release_dir}" ]]; then
    echo "current release changed during deployment verification" >&2
    false
fi

if [[ -n "${old_target}" && "${old_target}" == "${RELEASES_DIR}/"* && -d "${old_target}" ]]; then
    previous_tmp="${APP_ROOT}/.previous-${RELEASE_ID}-$$"
    ln -s "releases/$(basename -- "${old_target}")" "${previous_tmp}"
    mv -Tf "${previous_tmp}" "${PREVIOUS_LINK}"
fi

# Keep a bounded rollback history. Current and previous are protected
# explicitly even if an operator has changed their ordering or timestamps.
declare -A keep_releases=()
for protected_link in "${CURRENT_LINK}" "${PREVIOUS_LINK}"; do
    protected_target="$(readlink -f "${protected_link}" 2>/dev/null || true)"
    if [[ "${protected_target}" == "${RELEASES_DIR}/"* && -d "${protected_target}" ]]; then
        keep_releases["$(basename -- "${protected_target}")"]=1
    fi
done

mapfile -t release_names < <(
    find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' |
        sort -r
)
for release_name in "${release_names[@]}"; do
    [[ "${release_name}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{7,79}$ ]] || continue
    if [[ -n "${keep_releases[${release_name}]+present}" ]]; then
        continue
    fi
    if (( ${#keep_releases[@]} < MAX_RELEASE_HISTORY )); then
        keep_releases["${release_name}"]=1
    fi
done
for release_name in "${release_names[@]}"; do
    [[ "${release_name}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{7,79}$ ]] || continue
    if [[ -z "${keep_releases[${release_name}]+present}" ]]; then
        rm -rf --one-file-system -- "${RELEASES_DIR}/${release_name}"
    fi
done

sha_tmp="${APP_ROOT}/.DEPLOYED_SHA-${RELEASE_ID}-$$"
printf '%s\n' "${COMMIT_SHA}" > "${sha_tmp}"
mv -Tf "${sha_tmp}" "${DEPLOYED_SHA_FILE}"

trap - ERR
echo "deployed ${COMMIT_SHA} as ${RELEASE_ID}"
