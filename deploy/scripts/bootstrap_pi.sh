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
# - Optional: migrates config + logs from ~/yoyopod-core/ to /opt/yoyopod-prod/state/
# - Optional: installs a first release artifact after bootstrap
#
# Normally invoked by install_pi.sh, which downloads the source payload and
# calls this script with sudo -E so the unit runs as the invoking user.

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
install -m 0755 -o root -g root \
    "${REPO_ROOT}/deploy/scripts/prod_ota_guard.sh" \
    "${ROOT}/bin/prod-ota-guard.sh"

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

# 3b. Captive-portal DNS for on-device Wi‑Fi setup. While the device hosts its
# onboarding hotspot (NetworkManager ipv4=shared), resolve every name to the
# portal gateway so a phone auto-opens the setup page. NetworkManager includes
# dnsmasq-shared.d/* only while a shared connection is active, so this is inert
# during normal operation.
install -d -m 0755 -o root -g root /etc/NetworkManager/dnsmasq-shared.d
cat > "/etc/NetworkManager/dnsmasq-shared.d/010-yoyopod-captive.conf" <<'EOF'
# Written by bootstrap_pi.sh - YoYoPod Wi-Fi setup captive portal.
address=/#/10.42.0.1
EOF

# 3c. Authorize the network service to run the whole on-device Wi-Fi setup flow:
# scan, create/delete/activate NetworkManager profiles (AddConnection2, Delete,
# ActivateConnection), and bring up the "shared" AP hotspot. These polkit actions
# are only implicitly granted to active local sessions, but the service runs as a
# non-login systemd session, so without them NetworkManager denies AP activation
# ("Not authorized to share connections via wifi.") and profile changes. This
# mirrors the rule `yoyopod target deploy` installs for dev, so a prod bootstrap
# (which runs before any deploy) has the same grants. Match the actual service
# user (the units are patched to run as ${INVOKING_USER}), since that user is not
# necessarily a member of netdev; keep the netdev group as a fallback.
cat > "/etc/polkit-1/rules.d/50-yoyopod-wifi-share.rules" <<EOF
// Written by bootstrap_pi.sh - YoYoPod Wi-Fi setup authorization.
polkit.addRule(function(action, subject) {
    if ((subject.user == "${INVOKING_USER}" || subject.isInGroup("netdev")) &&
        (action.id == "org.freedesktop.NetworkManager.wifi.scan" ||
         action.id == "org.freedesktop.NetworkManager.settings.modify.system" ||
         action.id == "org.freedesktop.NetworkManager.network-control" ||
         action.id == "org.freedesktop.NetworkManager.checkpoint-rollback" ||
         action.id == "org.freedesktop.NetworkManager.wifi.share.protected" ||
         action.id == "org.freedesktop.NetworkManager.wifi.share.open")) {
        return polkit.Result.YES;
    }
});
EOF

# 4. EnvironmentFiles with the lane roots.
cat > "/etc/default/yoyopod-prod" <<EOF
# /etc/default/yoyopod-prod - written by bootstrap_pi.sh
YOYOPOD_ROOT=${ROOT}
YOYOPOD_STATE_DIR=${ROOT}/state
YOYOPOD_PID_FILE=${ROOT}/state/yoyopod.pid
YOYOPOD_SERVICE_NAME=yoyopod-prod.service
EOF

cat > "/etc/default/yoyopod-dev" <<EOF
# /etc/default/yoyopod-dev - written by bootstrap_pi.sh
YOYOPOD_DEV_ROOT=${DEV_ROOT}
YOYOPOD_DEV_CHECKOUT=${DEV_ROOT}/checkout
YOYOPOD_DEV_VENV=${DEV_ROOT}/venv
YOYOPOD_STATE_DIR=${DEV_ROOT}/state
YOYOPOD_PID_FILE=${DEV_ROOT}/state/yoyopod.pid
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
systemctl disable --now yoyopod-slot.service >/dev/null 2>&1 || true
legacy_template_units="$(
    {
        systemctl list-units --type=service --all --plain --no-legend 'yoyopod@*.service' 2>/dev/null || true
        systemctl list-unit-files --type=service --plain --no-legend 'yoyopod@*.service' 2>/dev/null || true
    } | awk '{print $1}' | sort -u
)"
if [ -n "${legacy_template_units}" ]; then
    systemctl disable --now ${legacy_template_units} >/dev/null 2>&1 || true
fi
rm -f \
    /etc/systemd/system/yoyopod@.service \
    /etc/systemd/system/yoyopod-slot.service \
    /etc/default/yoyopod
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

# 5. Optional migration from old config/logs -> /opt/yoyopod-prod/state/
if [ "${MIGRATE}" -eq 1 ]; then
    OLD="/home/${INVOKING_USER}/yoyopod-core"
    if [ -d "${OLD}" ]; then
        echo "bootstrap: migrating from ${OLD} -> ${ROOT}/state/"
        echo "bootstrap: legacy checkout is not copied; clone the repo into ${DEV_ROOT}/checkout before remote sync"
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

  # For the dev lane (PR testing):
  yoyopod target config edit
  yoyopod target mode activate dev
  yoyopod target deploy --branch <branch>

  # For prod slot installs:
  # The prod release CLI (yoyopod target release ...) returns in Round 3
  # of the CLI rebuild; see docs/ROADMAP.md.
  # Reinstalling a previously-shipped slot still works manually via
  # SSH + /opt/yoyopod-prod/bin/install-release.sh.

Then on the Pi:
  sudo systemctl enable --now yoyopod-prod.service

After bootstrap, the dev lane uses ${DEV_ROOT}/checkout for
'yoyopod target deploy' and the prod lane at ${ROOT} runs whichever
slot is symlinked at current/.

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
