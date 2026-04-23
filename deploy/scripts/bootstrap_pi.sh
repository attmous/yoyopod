#!/usr/bin/env bash
# deploy/scripts/bootstrap_pi.sh
#
# One-shot Pi bootstrap for slot deploys. Idempotent: safe to re-run.
#
# - Creates /opt/yoyopod/{releases,state,bin}
# - Installs yoyopod-slot.service + yoyopod-rollback.service
# - Writes /etc/default/yoyopod-slot with the invoking user/group
# - Copies deploy/scripts/rollback.sh to /opt/yoyopod/bin/rollback.sh
# - Copies deploy/scripts/install_release.sh to /opt/yoyopod/bin/install-release.sh
# - Optional: migrates config + data from ~/yoyopod-core/ to /opt/yoyopod/state/
# - Optional: installs a first release artifact after bootstrap
#
# Requires sudo. Invoke as the user who will run the app:
#   sudo -E deploy/scripts/bootstrap_pi.sh --migrate
# (The -E preserves $USER so the unit runs as the right account.)

set -euo pipefail

UNIT_DIR="/etc/systemd/system"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

ROOT="/opt/yoyopod"
MIGRATE=0
RELEASE_ARCHIVE=""
RELEASE_URL=""
for arg in "$@"; do
    case "$arg" in
        --migrate) MIGRATE=1 ;;
        --root=*) ROOT="${arg#--root=}" ;;
        --release-archive=*) RELEASE_ARCHIVE="${arg#--release-archive=}" ;;
        --release-url=*) RELEASE_URL="${arg#--release-url=}" ;;
        --root) echo "use --root=<path> form" >&2; exit 2 ;;
        --help|-h)
            echo "Usage: $0 [--migrate] [--root=<path>] [--release-archive=<path>] [--release-url=<url>]"
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

echo "bootstrap: user=${INVOKING_USER} group=${INVOKING_GROUP} root=${ROOT}"

# 1. Create directory skeleton.
install -d -m 0755 -o root -g root \
    "${ROOT}" "${ROOT}/bin"
install -d -m 0755 -o "${INVOKING_USER}" -g "${INVOKING_GROUP}" \
    "${ROOT}/releases" "${ROOT}/state" "${ROOT}/state/tmp"

# 2. Install rollback helper (owned by root, invoked by systemd).
install -m 0755 -o root -g root \
    "${REPO_ROOT}/deploy/scripts/rollback.sh" \
    "${ROOT}/bin/rollback.sh"
install -m 0755 -o root -g root \
    "${REPO_ROOT}/deploy/scripts/install_release.sh" \
    "${ROOT}/bin/install-release.sh"

# 3. Install systemd units.
install -m 0644 -o root -g root \
    "${REPO_ROOT}/deploy/systemd/yoyopod-slot.service" \
    "${UNIT_DIR}/yoyopod-slot.service"
install -m 0644 -o root -g root \
    "${REPO_ROOT}/deploy/systemd/yoyopod-rollback.service" \
    "${UNIT_DIR}/yoyopod-rollback.service"

# 4. EnvironmentFile with the user/group the slot service should run as.
cat > "/etc/default/yoyopod-slot" <<EOF
# /etc/default/yoyopod-slot - written by bootstrap_pi.sh
YOYOPOD_ROOT=${ROOT}
YOYOPOD_STATE_DIR=${ROOT}/state
EOF

# Patch User=/Group= into the unit (only if not already present).
# Guard makes re-runs idempotent: a second bootstrap won't inject duplicates.
if ! grep -q "^User=" "${UNIT_DIR}/yoyopod-slot.service"; then
    sed -i \
        -e "/^\[Service\]/a User=${INVOKING_USER}\nGroup=${INVOKING_GROUP}" \
        "${UNIT_DIR}/yoyopod-slot.service"
fi

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
    systemctl enable --now yoyopod-slot.service
fi

# 5. Optional migration from ~/yoyopod-core/ -> /opt/yoyopod/state/
if [ "${MIGRATE}" -eq 1 ]; then
    OLD="/home/${INVOKING_USER}/yoyopod-core"
    if [ -d "${OLD}" ]; then
        echo "bootstrap: migrating from ${OLD} -> ${ROOT}/state/"
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

bootstrap complete.  slot root: ${ROOT}

Next steps on the dev machine:
  uv run yoyopod remote release build-pi --output ./build/releases --channel dev
  yoyopod remote release push ./build/releases/<version>.tar.gz --first-deploy

Or install a published CI/release artifact directly:
  yoyopod remote release install-url <artifact-url> --first-deploy

Then on the Pi:
  sudo systemctl enable --now yoyopod-slot.service

After bootstrap, `yoyopod remote release ...` talks directly to ${ROOT}
and does not require this repo checkout to stay on the Pi. Keep the checkout
only if you still use `remote sync`, `remote validate`, or `remote setup`.

NOTE: the running app does not yet honour YOYOPOD_STATE_DIR/config/ -
the config loader still reads from the slot's relative ./config dir.
Migrated config in ${ROOT}/state/config/ is preserved for reference,
but the live app uses the config bundled into each slot.
If your old board relied on local-only config drift, merge those changes
into the repo's tracked config/ tree before the first slot build.

If you used a non-default --root, ensure slot.root in pi-deploy.local.yaml
matches: slot.root: ${ROOT}

EOF
