#!/usr/bin/env bash
# deploy/scripts/install_pi.sh
#
# Curl-friendly Raspberry Pi installer for the yoyopod dev/prod lane layout.
#
# Canonical fresh-board command:
#   curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
#
# Useful environment overrides:
#   YOYOPOD_INSTALL_REF=<git-ref>
#   YOYOPOD_INSTALL_REPO=<owner/repo>
#   YOYOPOD_INSTALL_SOURCE_URL=<tar.gz-url>

set -euo pipefail

REPO="${YOYOPOD_INSTALL_REPO:-moustafattia/yoyopod-core}"
REF="${YOYOPOD_INSTALL_REF:-main}"
SOURCE_URL="${YOYOPOD_INSTALL_SOURCE_URL:-https://codeload.github.com/${REPO}/tar.gz/${REF}}"

usage() {
    cat <<EOF
yoyopod Pi installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- [bootstrap args]

Examples:
  curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
  curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- --release-url=<artifact-url>
  curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- --migrate --release-url=<artifact-url>

Environment:
  YOYOPOD_INSTALL_REF         Git ref to install from; default: main
  YOYOPOD_INSTALL_REPO        GitHub owner/repo; default: moustafattia/yoyopod-core
  YOYOPOD_INSTALL_SOURCE_URL  Full source tarball URL; overrides repo/ref
EOF
}

for arg in "$@"; do
    case "$arg" in
        --help|-h)
            usage
            exit 0
            ;;
    esac
done

if [ "${EUID}" -ne 0 ]; then
    echo "install-pi: must run as root. Use: curl -fsSL <install-url> | sudo -E bash -s -- [args]" >&2
    exit 1
fi

for required in curl tar mktemp; do
    if ! command -v "${required}" >/dev/null 2>&1; then
        echo "install-pi: missing required command: ${required}" >&2
        exit 1
    fi
done

workdir="$(mktemp -d "${TMPDIR:-/tmp}/yoyopod-install.XXXXXX")"
cleanup() {
    rm -rf "${workdir}"
}
trap cleanup EXIT

archive="${workdir}/source.tar.gz"
source_dir="${workdir}/source"
mkdir -p "${source_dir}"

echo "install-pi: downloading yoyopod source from ${SOURCE_URL}"
curl -fsSL "${SOURCE_URL}" -o "${archive}"

echo "install-pi: extracting installer payload"
tar -xzf "${archive}" -C "${source_dir}" --strip-components=1

bootstrap="${source_dir}/deploy/scripts/bootstrap_pi.sh"
if [ ! -f "${bootstrap}" ]; then
    echo "install-pi: bootstrap script missing from downloaded source: ${bootstrap}" >&2
    exit 1
fi
chmod +x "${bootstrap}"

echo "install-pi: running board bootstrap"
"${bootstrap}" "$@"
