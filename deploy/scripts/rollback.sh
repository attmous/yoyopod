#!/usr/bin/env bash
# deploy/scripts/rollback.sh
#
# Rollback: swap `current` and `previous` symlinks, then restart the service.
# Intended to be called by yoyopod-prod-rollback.service (triggered by
# yoyopod-prod.service's OnFailure=) or manually by an operator.
#
# Contract:
#   * /opt/yoyopod-prod/current must be a symlink
#   * /opt/yoyopod-prod/previous must be a symlink
# If either precondition fails, exit nonzero and DO NOT touch anything.

set -euo pipefail

YOYOPOD_SERVICE_NAME_ENV="${YOYOPOD_SERVICE_NAME-}"
YOYOPOD_SERVICE_NAME_WAS_SET="${YOYOPOD_SERVICE_NAME+x}"
if [ -f /etc/default/yoyopod-prod ]; then
    # shellcheck disable=SC1091
    . /etc/default/yoyopod-prod
fi
if [ -n "${YOYOPOD_SERVICE_NAME_WAS_SET}" ]; then
    YOYOPOD_SERVICE_NAME="${YOYOPOD_SERVICE_NAME_ENV}"
fi

# Self-locate ROOT from $0 (script lives at <root>/bin/rollback.sh).
SCRIPT_PATH="$(readlink -f "$0")"
ROOT="$(dirname "$(dirname "${SCRIPT_PATH}")")"
SERVICE_NAME="${YOYOPOD_SERVICE_NAME:-yoyopod-prod.service}"
CURRENT="${ROOT}/current"
PREVIOUS="${ROOT}/previous"

if [ ! -L "${CURRENT}" ]; then
    echo "rollback: ${CURRENT} is not a symlink" >&2
    exit 2
fi
if [ ! -L "${PREVIOUS}" ]; then
    echo "rollback: ${PREVIOUS} is not a symlink (nothing to roll back to)" >&2
    exit 2
fi
CURRENT_TARGET="$(readlink -e "${CURRENT}" 2>/dev/null || true)"
PREVIOUS_TARGET="$(readlink -e "${PREVIOUS}" 2>/dev/null || true)"
if [ -z "${CURRENT_TARGET}" ]; then
    echo "rollback: ${CURRENT} target is dangling or does not resolve" >&2
    exit 2
fi
if [ -z "${PREVIOUS_TARGET}" ]; then
    echo "rollback: ${PREVIOUS} target is dangling or does not resolve" >&2
    exit 2
fi

# Swap current <-> previous atomically via a temp rename dance.
# Linux rename(2) of a symlink over another symlink on the same filesystem is atomic.
TMP="${ROOT}/current.tmp"
ln -sfn "${CURRENT_TARGET}" "${TMP}"
ln -sfn "${PREVIOUS_TARGET}" "${CURRENT}.new"
mv -T "${CURRENT}.new" "${CURRENT}"
mv -T "${TMP}" "${PREVIOUS}.new"
mv -T "${PREVIOUS}.new" "${PREVIOUS}"

echo "rollback: swapped current <- $(readlink "${CURRENT}")"

# Only attempt systemctl if we're on a systemd host (skipped in tests).
if command -v systemctl >/dev/null 2>&1 && [ -z "${YOYOPOD_SKIP_SYSTEMCTL:-}" ]; then
    systemctl reset-failed "${SERVICE_NAME}" || true
    systemctl restart "${SERVICE_NAME}"
fi
