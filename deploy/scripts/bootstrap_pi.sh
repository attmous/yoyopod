#!/usr/bin/env bash
# deploy/scripts/bootstrap_pi.sh
#
# One-shot Pi bootstrap for slot deploys. Idempotent: safe to re-run.
#
# - Creates /opt/yoyopod/{releases,state,bin}
# - Installs yoyopod-slot.service + yoyopod-rollback.service
# - Writes /etc/default/yoyopod-slot with the invoking user/group
# - Copies deploy/scripts/rollback.sh to /opt/yoyopod/bin/rollback.sh
# - Optional: migrates config + data from ~/yoyopod-core/ to /opt/yoyopod/state/
#
# Requires sudo. Invoke as the user who will run the app:
#   sudo -E deploy/scripts/bootstrap_pi.sh --migrate
# (The -E preserves $USER so the unit runs as the right account.)

set -euo pipefail

UNIT_DIR="/etc/systemd/system"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

ROOT="/opt/yoyopod"
MIGRATE=0
for arg in "$@"; do
    case "$arg" in
        --migrate) MIGRATE=1 ;;
        --root=*) ROOT="${arg#--root=}" ;;
        --root) echo "use --root=<path> form" >&2; exit 2 ;;
        --help|-h) echo "Usage: $0 [--migrate] [--root=<path>]"; exit 0 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

if [ "${EUID}" -ne 0 ]; then
    echo "bootstrap: must run as root (use sudo -E)" >&2
    exit 1
fi

INVOKING_USER="${SUDO_USER:-${USER:-pi}}"
INVOKING_GROUP="$(id -gn "${INVOKING_USER}")"

echo "bootstrap: user=${INVOKING_USER} group=${INVOKING_GROUP} root=${ROOT}"

# 1. Create directory skeleton.
install -d -m 0755 -o "${INVOKING_USER}" -g "${INVOKING_GROUP}" \
    "${ROOT}" "${ROOT}/releases" "${ROOT}/state" "${ROOT}/bin"

# 2. Install rollback helper (owned by root, invoked by systemd).
install -m 0755 -o root -g root \
    "${REPO_ROOT}/deploy/scripts/rollback.sh" \
    "${ROOT}/bin/rollback.sh"

# 3. Install systemd units.
install -m 0644 -o root -g root \
    "${REPO_ROOT}/deploy/systemd/yoyopod-slot.service" \
    "${UNIT_DIR}/yoyopod-slot.service"
install -m 0644 -o root -g root \
    "${REPO_ROOT}/deploy/systemd/yoyopod-rollback.service" \
    "${UNIT_DIR}/yoyopod-rollback.service"

# Substitute placeholder paths in the installed unit files when a non-default root is used.
if [ "${ROOT}" != "/opt/yoyopod" ]; then
    sed -i "s|/opt/yoyopod|${ROOT}|g" \
        "${UNIT_DIR}/yoyopod-slot.service" \
        "${UNIT_DIR}/yoyopod-rollback.service"
fi

# 4. EnvironmentFile with the user/group the slot service should run as.
cat > "/etc/default/yoyopod-slot" <<EOF
# /etc/default/yoyopod-slot — written by bootstrap_pi.sh
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

# 5. Optional migration from ~/yoyopod-core/ → /opt/yoyopod/state/
if [ "${MIGRATE}" -eq 1 ]; then
    OLD="/home/${INVOKING_USER}/yoyopod-core"
    if [ -d "${OLD}" ]; then
        echo "bootstrap: migrating from ${OLD} → ${ROOT}/state/"
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
  uv run python scripts/build_release.py --output ./build/releases --channel dev
  yoyopod remote release push ./build/releases/<version> --first-deploy

Then on the Pi:
  sudo systemctl enable --now yoyopod-slot.service

NOTE: the running app does not yet honour YOYOPOD_STATE_DIR/config/ —
the config loader still reads from the slot's relative ./config dir.
Migrated config in ${ROOT}/state/config/ will be unused until that
follow-up ticket lands. For now, the app runs with default settings.
This does NOT affect VoIP/music functionality if your old config was
already merged into the slot's config/ dir at build time.

If you used a non-default --root, ensure slot.root in pi-deploy.local.yaml
matches: slot.root: ${ROOT}

EOF
