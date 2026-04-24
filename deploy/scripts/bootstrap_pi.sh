#!/usr/bin/env bash
# deploy/scripts/bootstrap_pi.sh
#
# One-shot Pi bootstrap for dev/prod lane deploys. Idempotent: safe to re-run.
#
# - Creates /opt/yoyopod-prod/{releases,state,bin}
# - Creates /opt/yoyopod-dev/{checkout,venv,state,logs,tmp,bin}
# - Installs yoyopod-prod.service, yoyopod-prod-rollback.service, and yoyopod-dev.service
# - Writes /etc/default/yoyopod-prod and /etc/default/yoyopod-dev
# - Copies deploy/scripts/rollback.sh to /opt/yoyopod-prod/bin/rollback.sh
# - Copies deploy/scripts/install_release.sh to /opt/yoyopod-prod/bin/install-release.sh
# - Optional: migrates config + data from ~/yoyopod-core/ to /opt/yoyopod-prod/state/
# - Optional: installs a first release artifact after bootstrap
#
# Requires sudo. Invoke as the user who will run the app:
#   sudo -E deploy/scripts/bootstrap_pi.sh --migrate
# (The -E preserves $USER so the unit runs as the right account.)

set -euo pipefail

UNIT_DIR="/etc/systemd/system"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

ROOT="/opt/yoyopod-prod"
DEV_ROOT="/opt/yoyopod-dev"
MIGRATE=0
RELEASE_ARCHIVE=""
RELEASE_URL=""
for arg in "$@"; do
    case "$arg" in
        --migrate) MIGRATE=1 ;;
        --root=*) ROOT="${arg#--root=}" ;;
        --dev-root=*) DEV_ROOT="${arg#--dev-root=}" ;;
        --release-archive=*) RELEASE_ARCHIVE="${arg#--release-archive=}" ;;
        --release-url=*) RELEASE_URL="${arg#--release-url=}" ;;
        --root) echo "use --root=<path> form" >&2; exit 2 ;;
        --dev-root) echo "use --dev-root=<path> form" >&2; exit 2 ;;
        --help|-h)
            echo "Usage: $0 [--migrate] [--root=<path>] [--dev-root=<path>] [--release-archive=<path>] [--release-url=<url>]"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

if [ -n "${RELEASE_ARCHIVE}" ] && [ -n "${RELEASE_URL}" ]; then
    echo "bootstrap: pass only one of --release-archive or --release-url" >&2
    exit 2
fi

if [ "${EUID}" -ne 0 ]; then
    echo "bootstrap: must run as root (use sudo -E)" >&2
    exit 1
fi

INVOKING_USER="${SUDO_USER:-${USER:-pi}}"
INVOKING_GROUP="$(id -gn "${INVOKING_USER}")"

echo "bootstrap: user=${INVOKING_USER} group=${INVOKING_GROUP} prod_root=${ROOT} dev_root=${DEV_ROOT}"

# 1. Create directory skeleton.
install -d -m 0755 -o root -g root \
    "${ROOT}" "${ROOT}/bin" "${DEV_ROOT}" "${DEV_ROOT}/bin"
install -d -m 0755 -o "${INVOKING_USER}" -g "${INVOKING_GROUP}" \
    "${ROOT}/releases" "${ROOT}/state" "${ROOT}/state/tmp"
install -d -m 0755 -o "${INVOKING_USER}" -g "${INVOKING_GROUP}" \
    "${DEV_ROOT}/checkout" "${DEV_ROOT}/venv" "${DEV_ROOT}/state" \
    "${DEV_ROOT}/logs" "${DEV_ROOT}/tmp"

# 2. Install rollback helper (owned by root, invoked by systemd).
install -m 0755 -o root -g root \
    "${REPO_ROOT}/deploy/scripts/rollback.sh" \
    "${ROOT}/bin/rollback.sh"
install -m 0755 -o root -g root \
    "${REPO_ROOT}/deploy/scripts/install_release.sh" \
    "${ROOT}/bin/install-release.sh"

# 3. Install systemd units.
install -m 0644 -o root -g root \
    "${REPO_ROOT}/deploy/systemd/yoyopod-prod.service" \
    "${UNIT_DIR}/yoyopod-prod.service"
install -m 0644 -o root -g root \
    "${REPO_ROOT}/deploy/systemd/yoyopod-prod-rollback.service" \
    "${UNIT_DIR}/yoyopod-prod-rollback.service"
install -m 0644 -o root -g root \
    "${REPO_ROOT}/deploy/systemd/yoyopod-dev.service" \
    "${UNIT_DIR}/yoyopod-dev.service"

# 4. EnvironmentFiles with the lane roots.
cat > "/etc/default/yoyopod-prod" <<EOF
# /etc/default/yoyopod-prod - written by bootstrap_pi.sh
YOYOPOD_ROOT=${ROOT}
YOYOPOD_STATE_DIR=${ROOT}/state
YOYOPOD_SERVICE_NAME=yoyopod-prod.service
EOF

cat > "/etc/default/yoyopod-dev" <<EOF
# /etc/default/yoyopod-dev - written by bootstrap_pi.sh
YOYOPOD_DEV_ROOT=${DEV_ROOT}
YOYOPOD_DEV_CHECKOUT=${DEV_ROOT}/checkout
YOYOPOD_DEV_VENV=${DEV_ROOT}/venv
YOYOPOD_STATE_DIR=${DEV_ROOT}/state
EOF

# Patch User=/Group= into the unit (only if not already present).
# Guard makes re-runs idempotent: a second bootstrap won't inject duplicates.
for unit in yoyopod-prod.service yoyopod-dev.service; do
    if ! grep -q "^User=" "${UNIT_DIR}/${unit}"; then
        sed -i \
            -e "/^\[Service\]/a User=${INVOKING_USER}\nGroup=${INVOKING_GROUP}" \
            "${UNIT_DIR}/${unit}"
    fi
done

systemctl daemon-reload

if [ -n "${RELEASE_ARCHIVE}" ] || [ -n "${RELEASE_URL}" ]; then
    INSTALL_CMD=("${ROOT}/bin/install-release.sh" "--root=${ROOT}" "--first-deploy")
    if [ -n "${RELEASE_ARCHIVE}" ]; then
        INSTALL_CMD+=("--artifact=${RELEASE_ARCHIVE}")
    fi
    if [ -n "${RELEASE_URL}" ]; then
        INSTALL_CMD+=("--url=${RELEASE_URL}")
    fi
    echo "bootstrap: install initial release"
    "${INSTALL_CMD[@]}"
    systemctl enable --now yoyopod-prod.service
fi

# 5. Optional migration from ~/yoyopod-core/ -> /opt/yoyopod-prod/state/
if [ "${MIGRATE}" -eq 1 ]; then
    OLD="/home/${INVOKING_USER}/yoyopod-core"
    if [ -d "${OLD}" ]; then
        echo "bootstrap: migrating from ${OLD} -> ${ROOT}/state/"
        if [ ! -f "${DEV_ROOT}/checkout/pyproject.toml" ]; then
            echo "bootstrap: seeding dev checkout from ${OLD}"
            cp -a "${OLD}/." "${DEV_ROOT}/checkout/"
            rm -rf "${DEV_ROOT}/checkout/.venv" "${DEV_ROOT}/checkout/build" \
                "${DEV_ROOT}/checkout/logs"
            chown -R "${INVOKING_USER}:${INVOKING_GROUP}" "${DEV_ROOT}/checkout"
        fi
        for sub in config logs; do
            if [ -d "${OLD}/${sub}" ]; then
                install -d -o "${INVOKING_USER}" -g "${INVOKING_GROUP}" \
                    "${ROOT}/state/${sub}"
                cp -a "${OLD}/${sub}/." "${ROOT}/state/${sub}/"
            fi
        done
    else
        echo "bootstrap: no old install found at ${OLD}; skipping migration"
    fi
fi

cat <<EOF

bootstrap complete.

Prod lane root: ${ROOT}
Dev lane root:  ${DEV_ROOT}

Next steps on the dev machine:
  uv run yoyopod remote release build-pi --output ./build/releases --channel dev
  yoyopod remote release push ./build/releases/<version>.tar.gz --first-deploy

Or install a published CI/release artifact directly:
  yoyopod remote release install-url <artifact-url> --first-deploy

Then on the Pi:
  sudo systemctl enable --now yoyopod-prod.service

After bootstrap, 'yoyopod remote release ...' talks directly to the prod
lane at ${ROOT}. The dev lane uses ${DEV_ROOT}/checkout for 'remote sync',
'remote validate', and 'remote setup'.

NOTE: the running app does not yet honour YOYOPOD_STATE_DIR/config/ -
the config loader still reads from the slot's relative ./config dir.
Migrated config in ${ROOT}/state/config/ is preserved for reference,
but the live app uses the config bundled into each slot.
If your old board relied on local-only config drift, merge those changes
into the repo's tracked config/ tree before the first slot build.

If you used a non-default --root, ensure slot.root in pi-deploy.local.yaml
matches: slot.root: ${ROOT}

If you used a non-default --dev-root, ensure the dev lane config matches:
  lane.dev_root: ${DEV_ROOT}
  lane.dev_checkout: ${DEV_ROOT}/checkout
  lane.dev_venv: ${DEV_ROOT}/venv

EOF
