#!/usr/bin/env bash
# deploy/scripts/prod_ota_guard.sh
#
# ExecCondition-style guard for the future prod OTA service. It exits 0 only
# when the prod lane owns the app runtime and the dev lane is inactive.

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

DEV_SERVICE="${YOYOPOD_DEV_SERVICE:-yoyopod-dev.service}"
PROD_SERVICE="${YOYOPOD_SERVICE_NAME:-yoyopod-prod.service}"

if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet "${DEV_SERVICE}"; then
        echo "prod ota guard: dev lane is active; skipping prod OTA"
        exit 75
    fi

    if ! systemctl is-active --quiet "${PROD_SERVICE}"; then
        echo "prod ota guard: prod lane is not active; skipping prod OTA"
        exit 75
    fi
fi

exit 0
