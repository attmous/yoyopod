#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="/opt/yoyopod-web"
INCOMING_DIR="${APP_ROOT}/incoming"
INSTALLER_PATH="/usr/local/lib/yoyopod-web/install-release.sh"
DEPLOY_USER="yoyopod-web-deploy"
MAX_INCOMING_FILES=8
MAX_ARCHIVE_KIB=131072
STALE_ARCHIVE_MINUTES=60

if [[ "${EUID}" -ne 0 ]]; then
    echo "forced deploy command must run as root" >&2
    exit 1
fi

read -r action release_id commit_sha extra <<< "${SSH_ORIGINAL_COMMAND:-}"

valid_release_id() {
    [[ "${release_id:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{7,79}$ ]]
}

valid_commit_sha() {
    [[ "${commit_sha:-}" =~ ^[0-9a-f]{40}$ ]]
}

reject_extra_arguments() {
    if [[ -n "${extra:-}" ]]; then
        echo "unexpected deploy command arguments" >&2
        exit 2
    fi
}

case "${action:-}" in
    installer-sha256)
        [[ -z "${release_id:-}" && -z "${commit_sha:-}" && -z "${extra:-}" ]] || {
            echo "installer-sha256 takes no arguments" >&2
            exit 2
        }
        sha256sum "${INSTALLER_PATH}" | awk '{ print $1 }'
        ;;

    upload)
        valid_release_id || {
            echo "invalid release id" >&2
            exit 2
        }
        valid_commit_sha || {
            echo "invalid commit SHA" >&2
            exit 2
        }
        reject_extra_arguments

        # A canceled workflow can disconnect after upload but before deploy.
        # Expire both finalized and interrupted uploads so those failures can
        # never permanently exhaust the bounded incoming queue.
        find "${INCOMING_DIR}" \
            -mindepth 1 -maxdepth 1 -type f \
            \( -name 'yoyopod-web-*.tar.gz' -o -name '*.upload-*' \) \
            -mmin "+${STALE_ARCHIVE_MINUTES}" \
            -delete

        incoming_count="$(
            find "${INCOMING_DIR}" -mindepth 1 -maxdepth 1 -type f | wc -l
        )"
        if (( incoming_count >= MAX_INCOMING_FILES )); then
            echo "too many pending web release archives" >&2
            exit 1
        fi

        archive="${INCOMING_DIR}/yoyopod-web-${release_id}.tar.gz"
        temporary="${archive}.upload-$$"
        if [[ -e "${archive}" || -e "${temporary}" ]]; then
            echo "release archive already uploaded" >&2
            exit 1
        fi

        umask 0077
        ulimit -f "${MAX_ARCHIVE_KIB}"
        trap 'rm -f -- "${temporary}"' EXIT
        cat > "${temporary}"
        [[ -s "${temporary}" ]] || {
            echo "empty release archive" >&2
            exit 1
        }
        chown "${DEPLOY_USER}:${DEPLOY_USER}" "${temporary}"
        mv -T "${temporary}" "${archive}"
        trap - EXIT
        echo "uploaded ${release_id}"
        ;;

    deploy)
        valid_release_id || {
            echo "invalid release id" >&2
            exit 2
        }
        valid_commit_sha || {
            echo "invalid commit SHA" >&2
            exit 2
        }
        reject_extra_arguments

        archive="${INCOMING_DIR}/yoyopod-web-${release_id}.tar.gz"
        [[ -f "${archive}" ]] || {
            echo "release archive was not uploaded" >&2
            exit 1
        }
        if runuser -u "${DEPLOY_USER}" -- \
            "${INSTALLER_PATH}" "${archive}" "${release_id}" "${commit_sha}"; then
            rm -f -- "${archive}"
        else
            install_status="$?"
            rm -f -- "${archive}"
            exit "${install_status}"
        fi
        ;;

    status)
        [[ -z "${release_id:-}" && -z "${commit_sha:-}" && -z "${extra:-}" ]] || {
            echo "status takes no arguments" >&2
            exit 2
        }
        if [[ -f "${APP_ROOT}/DEPLOYED_SHA" ]]; then
            cat "${APP_ROOT}/DEPLOYED_SHA"
        else
            echo "not-deployed"
        fi
        ;;

    *)
        echo "allowed commands: installer-sha256, upload RELEASE_ID SHA, deploy RELEASE_ID SHA, status" >&2
        exit 2
        ;;
esac
