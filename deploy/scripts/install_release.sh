#!/usr/bin/env bash
# deploy/scripts/install_release.sh
#
# Install one self-contained slot artifact into /opt/yoyopod and flip it live.
# The artifact is expected to be the tar.gz emitted by scripts/build_release.py
# in a Linux/aarch64 build environment or by the CI slot build pipeline.

set -euo pipefail

ROOT="/opt/yoyopod"
ARTIFACT=""
URL=""
FIRST_DEPLOY=0
FORCE=0

for arg in "$@"; do
    case "$arg" in
        --artifact=*) ARTIFACT="${arg#--artifact=}" ;;
        --url=*) URL="${arg#--url=}" ;;
        --root=*) ROOT="${arg#--root=}" ;;
        --first-deploy) FIRST_DEPLOY=1 ;;
        --force) FORCE=1 ;;
        --help|-h)
            cat <<'EOF'
Usage: install_release.sh [--artifact=/path/to/release.tar.gz | --url=https://...]
                          [--root=/opt/yoyopod] [--first-deploy] [--force]
EOF
            exit 0
            ;;
        *)
            echo "install-release: unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

if [ "${EUID}" -ne 0 ]; then
    echo "install-release: must run as root" >&2
    exit 1
fi

if [ -n "${ARTIFACT}" ] && [ -n "${URL}" ]; then
    echo "install-release: pass only one of --artifact or --url" >&2
    exit 2
fi
if [ -z "${ARTIFACT}" ] && [ -z "${URL}" ]; then
    echo "install-release: missing --artifact or --url" >&2
    exit 2
fi

install -d -m 0755 "${ROOT}" "${ROOT}/releases" "${ROOT}/state" "${ROOT}/state/tmp" "${ROOT}/bin"

# Do not stage large artifacts in /tmp on the Pi: it is typically a small tmpfs.
TMP_ROOT="${ROOT}/state/tmp"
TMP_DIR="$(mktemp -d "${TMP_ROOT%/}/yoyopod-install.XXXXXX")"
trap 'rm -rf "${TMP_DIR}"' EXIT
STAGE_DIR="${TMP_DIR}/stage"
META_ENV="${TMP_DIR}/slot.env"
mkdir -p "${STAGE_DIR}"

_download_artifact() {
    local url="$1"
    local dest="$2"

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "${url}" -o "${dest}"
        return
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -qO "${dest}" "${url}"
        return
    fi
    python3 - "$url" "$dest" <<'PY'
import sys
import urllib.request

url, dest = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(url) as response, open(dest, "wb") as handle:
    handle.write(response.read())
PY
}

_extract_artifact() {
    local artifact_path="$1"
    local stage_dir="$2"
    local meta_env="$3"

    python3 - "$artifact_path" "$stage_dir" "$meta_env" <<'PY'
import json
import shlex
import sys
import tarfile
from pathlib import Path

artifact = Path(sys.argv[1]).resolve()
stage_dir = Path(sys.argv[2]).resolve()
meta_env = Path(sys.argv[3]).resolve()

if not artifact.is_file():
    raise SystemExit(f"install-release: artifact not found: {artifact}")

with tarfile.open(artifact, "r:*") as handle:
    for member in handle.getmembers():
        target = (stage_dir / member.name).resolve()
        try:
            target.relative_to(stage_dir)
        except ValueError as exc:
            raise SystemExit(
                f"install-release: tarball contains unsafe path: {member.name}"
            ) from exc
    try:
        handle.extractall(stage_dir, filter="data")
    except TypeError:
        handle.extractall(stage_dir)

manifests = [candidate.parent for candidate in stage_dir.rglob("manifest.json")]
if len(manifests) != 1:
    raise SystemExit(
        f"install-release: expected exactly one slot manifest in {artifact}, found {len(manifests)}"
    )

slot_dir = manifests[0].resolve()
manifest_path = slot_dir / "manifest.json"
data = json.loads(manifest_path.read_text(encoding="utf-8"))
version = str(data.get("version", "")).strip()
if not version:
    raise SystemExit(f"install-release: manifest missing version: {manifest_path}")

meta_env.write_text(
    f"VERSION={shlex.quote(version)}\nSLOT_DIR={shlex.quote(str(slot_dir))}\n",
    encoding="utf-8",
)
PY
}

_preflight_slot() {
    local slot_dir="$1"
    local python_bin="${slot_dir}/venv/bin/python"
    local app_path="${slot_dir}/app"
    local manifest_path="${slot_dir}/manifest.json"

    if [ ! -x "${python_bin}" ]; then
        echo "install-release: slot runtime missing: ${python_bin}" >&2
        return 1
    fi

    YOYOPOD_APP_PATH="${app_path}" \
    YOYOPOD_RELEASE_MANIFEST="${manifest_path}" \
    "${python_bin}" -c \
        "import os, sys; sys.path.insert(0, os.environ['YOYOPOD_APP_PATH']); from yoyopod_cli.health import app; app()" \
        preflight --slot "${slot_dir}"
}

_live_probe() {
    local root="$1"
    local version="$2"

    for _ in $(seq 1 60); do
        if systemctl is-active --quiet yoyopod-slot.service; then
            local pid
            pid="$(systemctl show -p MainPID --value yoyopod-slot.service 2>/dev/null || true)"
            if [ -n "${pid}" ] && [ "${pid}" != "0" ]; then
                local current_path cwd
                current_path="$(readlink -f "${root}/current" 2>/dev/null || true)"
                cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
                if [ -n "${current_path}" ] && [ "${cwd}" = "${current_path}" ] && \
                    [ "$(basename "${current_path}")" = "${version}" ]; then
                    echo "install-release: live version=${version}"
                    return 0
                fi
            fi
        fi
        sleep 1
    done

    echo "install-release: live probe failed for ${version}" >&2
    return 1
}

ARTIFACT_PATH="${ARTIFACT}"
if [ -n "${URL}" ]; then
    ARTIFACT_PATH="${TMP_DIR}/release.tar.gz"
    echo "install-release: download ${URL}"
    _download_artifact "${URL}" "${ARTIFACT_PATH}"
fi

_extract_artifact "${ARTIFACT_PATH}" "${STAGE_DIR}" "${META_ENV}"
# shellcheck disable=SC1090
source "${META_ENV}"

TARGET_DIR="${ROOT}/releases/${VERSION}"
CURRENT_TARGET="$(readlink -f "${ROOT}/current" 2>/dev/null || true)"

if [ -d "${TARGET_DIR}" ]; then
    if [ -n "${CURRENT_TARGET}" ] && [ "${CURRENT_TARGET}" = "$(readlink -f "${TARGET_DIR}")" ]; then
        echo "install-release: refusing to overwrite active slot ${VERSION}" >&2
        exit 2
    fi
    if [ "${FORCE}" -ne 1 ]; then
        echo "install-release: slot ${VERSION} already exists; pass --force to overwrite" >&2
        exit 2
    fi
    rm -rf "${TARGET_DIR}"
fi

if [ "${FIRST_DEPLOY}" -ne 1 ] && [ ! -L "${ROOT}/previous" ]; then
    echo "install-release: no rollback path; rerun with --first-deploy to acknowledge" >&2
    exit 2
fi

cp -a "${SLOT_DIR}" "${TARGET_DIR}"
chmod 755 "${TARGET_DIR}/bin/launch"

echo "install-release: preflight ${VERSION}"
_preflight_slot "${TARGET_DIR}"

PREVIOUS_LINK="${ROOT}/previous"
CURRENT_LINK="${ROOT}/current"
PREV_TARGET="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
if [ -n "${PREV_TARGET}" ]; then
    ln -sfn "${PREV_TARGET}" "${PREVIOUS_LINK}.new"
    mv -T "${PREVIOUS_LINK}.new" "${PREVIOUS_LINK}"
fi
ln -sfn "${TARGET_DIR}" "${CURRENT_LINK}.new"
mv -T "${CURRENT_LINK}.new" "${CURRENT_LINK}"

if [ "${YOYOPOD_SKIP_SYSTEMCTL:-0}" = "1" ]; then
    echo "install-release: skipping systemctl"
elif command -v systemctl >/dev/null 2>&1; then
    echo "install-release: restart yoyopod-slot.service"
    systemctl restart yoyopod-slot.service
    if ! _live_probe "${ROOT}" "${VERSION}"; then
        if [ -x "${ROOT}/bin/rollback.sh" ] && [ -L "${ROOT}/previous" ]; then
            echo "install-release: live probe failed, attempting rollback" >&2
            if ! "${ROOT}/bin/rollback.sh"; then
                echo "install-release: rollback also failed; system state unknown" >&2
            fi
        fi
        exit 1
    fi
else
    echo "install-release: systemctl not found; slot installed but not started"
fi

echo "install-release: installed ${VERSION}"
