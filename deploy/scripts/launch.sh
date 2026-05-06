#!/usr/bin/env bash
# deploy/scripts/launch.sh
#
# Slot launcher - run from systemd via /opt/yoyopod-prod/current/bin/launch.
# Resolves the slot dir from $0, sets env vars the app needs, exec's the Rust runtime.
#
# This script MUST work when invoked through the `current` symlink. We
# dereference that symlink once to get the real slot directory so our
# $SLOT_DIR variable doesn't chase the symlink mid-run.

set -euo pipefail

# Resolve the real directory this script lives in (following the current symlink).
SCRIPT_PATH="$(readlink -f "$0")"
SLOT_DIR="$(dirname "$(dirname "$SCRIPT_PATH")")"

export YOYOPOD_RELEASE_MANIFEST="${SLOT_DIR}/manifest.json"
export YOYOPOD_STATE_DIR="${YOYOPOD_STATE_DIR:-/opt/yoyopod-prod/state}"
export PYTHONPATH="${SLOT_DIR}/app"
export PYTHONUNBUFFERED=1

PYTHON_RUNTIME_LIB="${SLOT_DIR}/python/lib"
LVGL_NATIVE_LIB="${SLOT_DIR}/app/yoyopod/ui/lvgl_binding/native/build/lvgl/lib"
LVGL_NATIVE_BUILD="${SLOT_DIR}/app/yoyopod/ui/lvgl_binding/native/build"
export LD_LIBRARY_PATH="${PYTHON_RUNTIME_LIB}:${LVGL_NATIVE_LIB}:${LVGL_NATIVE_BUILD}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

# Create the state dir if missing (first boot after bootstrap).
mkdir -p "${YOYOPOD_STATE_DIR}"

RUNTIME="${SLOT_DIR}/app/device/runtime/build/yoyopod-runtime"
if [ ! -x "${RUNTIME}" ]; then
    echo "slot runtime missing: ${RUNTIME}" >&2
    exit 1
fi

cd "${SLOT_DIR}"
exec "${RUNTIME}" --config-dir "${SLOT_DIR}/config" "$@"
