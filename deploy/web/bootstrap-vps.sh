#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "bootstrap-vps.sh must run as root" >&2
    exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_USER="yoyopod-web-deploy"
APP_ROOT="/opt/yoyopod-web"
NGINX_AVAILABLE="/etc/nginx/sites-available/yoyopod"
NGINX_ENABLED="/etc/nginx/sites-enabled/yoyopod"
SERVICE_PATH="/etc/systemd/system/yoyopod-notify.service"
SUDOERS_PATH="/etc/sudoers.d/yoyopod-web-deploy"
INSTALLER_DIR="/usr/local/lib/yoyopod-web"
INSTALLER_PATH="${INSTALLER_DIR}/install-release.sh"
SSH_COMMAND_PATH="/usr/local/sbin/yoyopod-web-ssh-command"
ROOT_AUTHORIZED_KEYS="/root/.ssh/authorized_keys"
PUBLIC_KEY_FILE="${1:-}"

for command_name in curl flock nginx node runuser sha256sum sudo systemctl tar useradd usermod visudo; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        echo "required command is missing: ${command_name}" >&2
        exit 1
    fi
done

if [[ ! -f "${SCRIPT_DIR}/yoyopod.nginx.conf" ||
      ! -f "${SCRIPT_DIR}/yoyopod-notify.service" ||
      ! -f "${SCRIPT_DIR}/install-release.sh" ||
      ! -f "${SCRIPT_DIR}/ssh-command.sh" ]]; then
    echo "run bootstrap-vps.sh from the complete deploy/web bundle" >&2
    exit 1
fi

# Refuse to shadow a site configured through any effective nginx include.
# `nginx -T` expands the actual configuration, including conf.d and custom
# include trees. Re-running this bootstrap is allowed, so its own enabled
# server file is excluded.
nginx_dump="$(nginx -T 2>/dev/null)"
mapfile -t conflicting_configs < <(
    printf '%s\n' "${nginx_dump}" |
        awk '
            $1 == "#" && $2 == "configuration" && $3 == "file" {
                file = $4
                sub(/:$/, "", file)
                next
            }
            /^[[:space:]]*server_name[[:space:]]/ &&
                /(yoyopod\.com|docs\.yoyopod\.com)/ {
                print file
            }
        ' |
        grep -Fvx -- "${NGINX_AVAILABLE}" |
        grep -Fvx -- "${NGINX_ENABLED}" |
        sort -u || true
)
if (( ${#conflicting_configs[@]} > 0 )); then
    echo "refusing to install: yoyopod server_name already appears in:" >&2
    printf '  %s\n' "${conflicting_configs[@]}" >&2
    exit 1
fi

if [[ -e "${NGINX_ENABLED}" && ! -L "${NGINX_ENABLED}" ]]; then
    echo "refusing to replace non-symlink nginx config: ${NGINX_ENABLED}" >&2
    exit 1
fi
if [[ -L "${NGINX_ENABLED}" ]]; then
    enabled_target="$(readlink "${NGINX_ENABLED}")"
    if [[ "${enabled_target}" != "${NGINX_AVAILABLE}" ]]; then
        echo "refusing to retarget existing nginx symlink: ${NGINX_ENABLED}" >&2
        exit 1
    fi
fi

if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
    useradd \
        --system \
        --home-dir /nonexistent \
        --shell /usr/sbin/nologin \
        --user-group \
        "${DEPLOY_USER}"
fi
usermod --shell /usr/sbin/nologin "${DEPLOY_USER}"

install -d -m 0755 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" \
    "${APP_ROOT}" "${APP_ROOT}/releases" "${APP_ROOT}/incoming"
install -d -m 0755 -o root -g root "${INSTALLER_DIR}"
install -m 0755 -o root -g root \
    "${SCRIPT_DIR}/install-release.sh" "${INSTALLER_PATH}"
install -m 0755 -o root -g root \
    "${SCRIPT_DIR}/ssh-command.sh" "${SSH_COMMAND_PATH}"

if [[ -n "${PUBLIC_KEY_FILE}" ]]; then
    if [[ ! -f "${PUBLIC_KEY_FILE}" ]]; then
        echo "public key file does not exist: ${PUBLIC_KEY_FILE}" >&2
        exit 1
    fi
    public_key="$(tr -d '\r\n' < "${PUBLIC_KEY_FILE}")"
    if [[ ! "${public_key}" =~ ^ssh-(ed25519|rsa)[[:space:]] ]]; then
        echo "public key file is not an OpenSSH public key" >&2
        exit 1
    fi
    key_material="$(awk '{ print $1 " " $2 }' <<< "${public_key}")"
    restricted_key="restrict,command=\"${SSH_COMMAND_PATH}\" ${public_key}"
    install -d -m 0700 -o root -g root /root/.ssh
    touch "${ROOT_AUTHORIZED_KEYS}"
    chmod 0600 "${ROOT_AUTHORIZED_KEYS}"
    if grep -qF -- "${key_material}" "${ROOT_AUTHORIZED_KEYS}"; then
        if ! grep -qxF -- "${restricted_key}" "${ROOT_AUTHORIZED_KEYS}"; then
            echo "the deploy key already exists without the required forced-command restriction" >&2
            exit 1
        fi
    else
        printf '%s\n' "${restricted_key}" >> "${ROOT_AUTHORIZED_KEYS}"
    fi
fi

# Certbot's nginx plugin edits the live vhost in place. Preserve that file on
# later bootstrap runs so installing a newer release handler cannot remove
# HTTPS listeners or certificate directives.
if [[ -f "${NGINX_AVAILABLE}" ]] &&
   grep -qiE 'managed by Certbot|^[[:space:]]*ssl_certificate(_key)?[[:space:]]' \
       "${NGINX_AVAILABLE}"; then
    echo "preserving TLS-managed nginx config: ${NGINX_AVAILABLE}"
else
    install -m 0644 "${SCRIPT_DIR}/yoyopod.nginx.conf" "${NGINX_AVAILABLE}"
fi
ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
install -m 0644 "${SCRIPT_DIR}/yoyopod-notify.service" "${SERVICE_PATH}"

sudoers_tmp="$(mktemp)"
trap 'rm -f -- "${sudoers_tmp}"' EXIT
cat > "${sudoers_tmp}" <<EOF
${DEPLOY_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart yoyopod-notify.service
EOF
chmod 0440 "${sudoers_tmp}"
visudo -cf "${sudoers_tmp}"
install -m 0440 "${sudoers_tmp}" "${SUDOERS_PATH}"

systemctl daemon-reload
nginx -t
systemctl reload nginx

echo "yoyopod web VPS bootstrap complete"
echo "release owner: ${DEPLOY_USER} (no login shell)"
echo "release root: ${APP_ROOT}"
if [[ -z "${PUBLIC_KEY_FILE}" ]]; then
    echo "warning: no SSH deploy key was installed"
fi
