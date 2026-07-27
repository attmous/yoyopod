#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="/opt/yoyopod-web"
RELEASES_DIR="${APP_ROOT}/releases"
CURRENT_LINK="${APP_ROOT}/current"
PREVIOUS_LINK="${APP_ROOT}/previous"
DEPLOYED_SHA_FILE="${APP_ROOT}/DEPLOYED_SHA"
EXPECTED_USER="yoyopod-web-deploy"
NGINX_CONFIG="/etc/nginx/sites-available/yoyopod"

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

while IFS= read -r archive_listing; do
    entry_type="${archive_listing:0:1}"
    if [[ "${entry_type}" != "-" && "${entry_type}" != "d" ]]; then
        echo "release archives may contain only regular files and directories" >&2
        exit 1
    fi
done < <(LC_ALL=C tar -tvzf "${ARCHIVE}")

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
            --resolve "${host}:${origin_port}:127.0.0.1" \
            "${origin_scheme}://${host}${path}"
    )"
    if [[ "${actual}" != "${expected}" ]]; then
        echo "${host}${path}: expected HTTP ${expected}, received ${actual}" >&2
        return 1
    fi
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

# The built page is the source of truth for whether signup is exposed. Closed
# releases must see nginx's 404. Once the form is deliberately enabled, a safe
# GET reaches the collector and must return its method-not-allowed response;
# no test address is submitted.
if grep -Fq 'action="/api/notify"' "${release_dir}/root/index.html"; then
    assert_status "yoyopod.com" "/api/notify" "405"
else
    assert_status "yoyopod.com" "/api/notify" "404"
fi

if [[ -n "${old_target}" && "${old_target}" == "${RELEASES_DIR}/"* && -d "${old_target}" ]]; then
    previous_tmp="${APP_ROOT}/.previous-${RELEASE_ID}-$$"
    ln -s "releases/$(basename -- "${old_target}")" "${previous_tmp}"
    mv -Tf "${previous_tmp}" "${PREVIOUS_LINK}"
fi

sha_tmp="${APP_ROOT}/.DEPLOYED_SHA-${RELEASE_ID}-$$"
printf '%s\n' "${COMMIT_SHA}" > "${sha_tmp}"
mv -Tf "${sha_tmp}" "${DEPLOYED_SHA_FILE}"

trap - ERR
echo "deployed ${COMMIT_SHA} as ${RELEASE_ID}"
