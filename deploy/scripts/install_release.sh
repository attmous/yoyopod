#!/usr/bin/env bash
# deploy/scripts/install_release.sh
#
# Install one self-contained slot artifact into /opt/yoyopod-prod and flip it live.
# The artifact is expected to be the tar.gz emitted by scripts/build_release.py
# in a Linux/aarch64 build environment or by the CI slot build pipeline.

set -euo pipefail

YOYOPOD_ROOT_ENV="${YOYOPOD_ROOT-}"
YOYOPOD_ROOT_WAS_SET="${YOYOPOD_ROOT+x}"
YOYOPOD_SERVICE_NAME_ENV="${YOYOPOD_SERVICE_NAME-}"
YOYOPOD_SERVICE_NAME_WAS_SET="${YOYOPOD_SERVICE_NAME+x}"
if [ -f /etc/default/yoyopod-prod ]; then
    # shellcheck disable=SC1091
    . /etc/default/yoyopod-prod
fi
if [ -n "${YOYOPOD_ROOT_WAS_SET}" ]; then
    YOYOPOD_ROOT="${YOYOPOD_ROOT_ENV}"
fi
if [ -n "${YOYOPOD_SERVICE_NAME_WAS_SET}" ]; then
    YOYOPOD_SERVICE_NAME="${YOYOPOD_SERVICE_NAME_ENV}"
fi

ROOT="${YOYOPOD_ROOT:-/opt/yoyopod-prod}"
SERVICE_NAME="${YOYOPOD_SERVICE_NAME:-yoyopod-prod.service}"
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
                          [--root=/opt/yoyopod-prod] [--first-deploy] [--force]
EOF
            exit 0
            ;;
        *)
            echo "install-release: unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

if [ "${EUID}" -ne 0 ] && [ "${YOYOPOD_INSTALL_RELEASE_ALLOW_NON_ROOT:-0}" != "1" ]; then
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
import re
import shlex
import shutil
import sys
import tarfile
from pathlib import Path

artifact = Path(sys.argv[1]).resolve()
stage_dir = Path(sys.argv[2]).resolve()
meta_env = Path(sys.argv[3]).resolve()

if not artifact.is_file():
    raise SystemExit(f"install-release: artifact not found: {artifact}")


def extract_tar_member_fallback(handle: tarfile.TarFile, member: tarfile.TarInfo) -> None:
    target = stage_dir / member.name
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if member.issym():
        target.symlink_to(member.linkname)
        return
    source = handle.extractfile(member)
    if source is None:
        raise SystemExit(f"install-release: tarball member has no payload: {member.name}")
    with source, target.open("wb") as output:
        shutil.copyfileobj(source, output)
    target.chmod(member.mode & 0o777)


with tarfile.open(artifact, "r:*") as handle:
    members = handle.getmembers()
    member_names = [member.name.rstrip("/") for member in members]
    for member in members:
        if member.islnk():
            raise SystemExit(f"install-release: tarball contains unsafe hard link: {member.name}")
        if member.issym():
            link_target = ((stage_dir / member.name).parent / member.linkname).resolve()
            try:
                link_target.relative_to(stage_dir)
            except ValueError as exc:
                raise SystemExit(
                    f"install-release: tarball contains unsafe link: {member.name}"
                ) from exc
            prefix = member.name.rstrip("/") + "/"
            if any(name.startswith(prefix) for name in member_names):
                raise SystemExit(
                    f"install-release: tarball contains unsafe link prefix: {member.name}"
                )
        elif not (member.isdir() or member.isreg()):
            raise SystemExit(
                f"install-release: tarball contains unsafe member type: {member.name}"
            )
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
        for member in members:
            extract_tar_member_fallback(handle, member)

manifests = [candidate.parent for candidate in stage_dir.rglob("manifest.json")]
if len(manifests) != 1:
    raise SystemExit(
        f"install-release: expected exactly one slot manifest in {artifact}, found {len(manifests)}"
    )

slot_dir = manifests[0].resolve()
manifest_path = slot_dir / "manifest.json"
data = json.loads(manifest_path.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    raise SystemExit(f"install-release: manifest root must be an object: {manifest_path}")
version = str(data.get("version", "")).strip()
if not version:
    raise SystemExit(f"install-release: manifest missing version: {manifest_path}")
if version in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
    raise SystemExit(f"install-release: unsafe version in manifest: {version!r}")

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
    PYTHONDONTWRITEBYTECODE=1 \
    "${python_bin}" -c \
        "import os, sys; sys.path.insert(0, os.environ['YOYOPOD_APP_PATH']); from yoyopod_cli.health import app; app()" \
        preflight --slot "${slot_dir}"
}

_live_probe() {
    local root="$1"
    local version="$2"
    local stable=0
    local required_stable=120
    local last_pid=""

    for _ in $(seq 1 180); do
        if systemctl is-active --quiet "${SERVICE_NAME}"; then
            local pid
            pid="$(systemctl show -p MainPID --value "${SERVICE_NAME}" 2>/dev/null || true)"
            if [ -n "${pid}" ] && [ "${pid}" != "0" ]; then
                local current_path cwd
                current_path="$(readlink -f "${root}/current" 2>/dev/null || true)"
                cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
                if [ -n "${current_path}" ] && [ "${cwd}" = "${current_path}" ] && \
                    [ "$(basename "${current_path}")" = "${version}" ]; then
                    if [ "${pid}" != "${last_pid}" ]; then
                        stable=0
                        last_pid="${pid}"
                    fi
                    stable=$((stable + 1))
                    if [ "${stable}" -ge "${required_stable}" ]; then
                        echo "install-release: live version=${version}"
                        return 0
                    fi
                else
                    stable=0
                fi
            else
                stable=0
            fi
        else
            stable=0
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

if [ "${FIRST_DEPLOY}" -ne 1 ]; then
    if [ ! -L "${ROOT}/previous" ]; then
        echo "install-release: no rollback path; rerun with --first-deploy to acknowledge" >&2
        exit 2
    fi
    if ! readlink -e "${ROOT}/previous" >/dev/null 2>&1; then
        echo "install-release: previous rollback target is dangling" >&2
        exit 2
    fi
fi

cp -a "${SLOT_DIR}" "${TARGET_DIR}"
if [ "${EUID}" -eq 0 ]; then
    RELEASE_OWNER="$(stat -c '%u:%g' "${ROOT}/releases")"
    chown -R "${RELEASE_OWNER}" "${TARGET_DIR}"
fi
chmod 755 "${TARGET_DIR}/bin/launch"

echo "install-release: preflight ${VERSION}"
_preflight_slot "${TARGET_DIR}"

PREVIOUS_LINK="${ROOT}/previous"
CURRENT_LINK="${ROOT}/current"
PREV_TARGET=""
if [ -L "${CURRENT_LINK}" ]; then
    PREV_TARGET="$(readlink -e "${CURRENT_LINK}" 2>/dev/null || true)"
fi
if [ -n "${PREV_TARGET}" ]; then
    ln -sfn "${PREV_TARGET}" "${PREVIOUS_LINK}.new"
    mv -T "${PREVIOUS_LINK}.new" "${PREVIOUS_LINK}"
fi
ln -sfn "${TARGET_DIR}" "${CURRENT_LINK}.new"
mv -T "${CURRENT_LINK}.new" "${CURRENT_LINK}"

if [ "${YOYOPOD_SKIP_SYSTEMCTL:-0}" = "1" ]; then
    echo "install-release: skipping systemctl"
elif command -v systemctl >/dev/null 2>&1; then
    echo "install-release: restart ${SERVICE_NAME}"
    systemctl reset-failed "${SERVICE_NAME}" || true
    if ! systemctl restart "${SERVICE_NAME}"; then
        if [ -x "${ROOT}/bin/rollback.sh" ] && [ -L "${ROOT}/previous" ]; then
            echo "install-release: restart failed, attempting rollback" >&2
            if ! YOYOPOD_SERVICE_NAME="${SERVICE_NAME}" "${ROOT}/bin/rollback.sh"; then
                echo "install-release: rollback also failed; system state unknown" >&2
            fi
        fi
        exit 1
    fi
    if ! _live_probe "${ROOT}" "${VERSION}"; then
        if [ -x "${ROOT}/bin/rollback.sh" ] && [ -L "${ROOT}/previous" ]; then
            echo "install-release: live probe failed, attempting rollback" >&2
            if ! YOYOPOD_SERVICE_NAME="${SERVICE_NAME}" "${ROOT}/bin/rollback.sh"; then
                echo "install-release: rollback also failed; system state unknown" >&2
            fi
        fi
        exit 1
    fi
else
    echo "install-release: systemctl not found; slot installed but not started"
fi

echo "install-release: installed ${VERSION}"
