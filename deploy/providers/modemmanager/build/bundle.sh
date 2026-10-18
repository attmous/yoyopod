#!/usr/bin/env bash
# Sourcing this file defines only private functions; it performs no work.
bundle_python() {
  local provider_root
  provider_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) || return
  python3 -I -B - "$provider_root/build/package.py" "$@" <<'PY'
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

spec = importlib.util.spec_from_file_location("provider_package", sys.argv[1])
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
check = package.check
BINARY_PATHS = (
    "device/cloud/build/yoyopod-cloud-host",
    "device/media/build/yoyopod-media-host",
    "device/network/build/yoyopod-network-host",
    "device/onpi/build/yoyopod-on-pi",
    "device/power/build/yoyopod-power-host",
    "device/runtime/build/yoyopod-runtime",
    "device/speech/build/yoyopod-speech-host",
    "device/ui/build/yoyopod-ui-host",
    "device/voip/build/yoyopod-voip-host",
)


def checked(value, directory=False):
    raw = Path(value)
    check(".." not in raw.parts, "parent component in input path")
    path = Path(os.path.abspath(raw))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        mode = current.lstat().st_mode
        check(not stat.S_ISLNK(mode), "symlink in input path")
        check(stat.S_ISDIR(mode) if current != path or directory else stat.S_ISREG(mode),
              "non-regular input path")
    return path


def canonical(name):
    check(isinstance(name, str) and name and "\\" not in name and ":" not in name
          and not any(ord(char) < 32 or ord(char) == 127 for char in name)
          and all(part not in ("", ".", "..") for part in name.split("/")),
          "noncanonical archive path")
    return name


def read_json(data):
    def pairs(rows):
        result = {}
        for key, value in rows:
            check(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def identity(sha, run):
    check(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "invalid expected SHA")
    check(re.fullmatch(r"[0-9]+", run) is not None, "invalid expected run")


def provider_files(manifest):
    names = {"manifest.json", "profile.json"}
    for section in ("packages", "source_files", "reports"):
        for row in manifest[section]:
            name = canonical(row["file"])
            check(name not in names, "duplicate provider path")
            names.add(name)
    return names


def validate_provider(root, sha, run):
    manifest = package.validate_manifest(root)
    check((manifest["repo_sha"], manifest["ci_run_id"]) == (sha, run), "provider SHA/run mismatch")
    daemon_package = next(row for row in manifest["packages"] if row["name"] == "modemmanager")
    # Inspect actual daemon bytes without running maintainer scripts or extracting
    # package-directed paths. The candidate package itself is already hash-bound.
    with tempfile.TemporaryFile() as payload:
        subprocess.run(["dpkg-deb", "--fsys-tarfile", str(root / daemon_package["file"])],
                       stdout=payload, check=True)
        payload.seek(0)
        with tarfile.open(fileobj=payload, mode="r:") as archive:
            matches = [member for member in archive.getmembers()
                       if member.name in ("./usr/sbin/ModemManager", "usr/sbin/ModemManager")]
            check(len(matches) == 1 and matches[0].isfile(), "missing/non-regular packaged daemon")
            with archive.extractfile(matches[0]) as stream:
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                actual = digest.hexdigest()
            check(actual == manifest["daemon_sha256"], "packaged daemon hash mismatch")
    return manifest


def copy_regular(source, destination):
    source = checked(source)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(source, flags), "rb") as stream:
        mode = os.fstat(stream.fileno()).st_mode
        check(stat.S_ISREG(mode), "non-regular opened input")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as target:
            shutil.copyfileobj(stream, target)
        destination.chmod(stat.S_IMODE(mode) & 0o777)


def directories(files):
    return {str(parent) for name in files for parent in Path(name).parents if str(parent) != "."}


def raw_ustar(path):
    # TarInfo.frombuf checks the checksum and decodes numeric size fields, but
    # also normalizes directory slashes. Inspect the original fields first;
    # never let a logical reader consume hidden GNU/PAX extension headers.
    def text(field):
        value, separator, padding = field.partition(b"\0")
        check(not separator or not padding.strip(b"\0"), "nonzero USTAR name padding")
        return value.decode("utf-8", "strict")

    with gzip.open(path, "rb") as stream:
        while True:
            header = stream.read(tarfile.BLOCKSIZE)
            check(len(header) == tarfile.BLOCKSIZE, "truncated USTAR header")
            if header == b"\0" * tarfile.BLOCKSIZE:
                check(stream.read(tarfile.BLOCKSIZE) == b"\0" * tarfile.BLOCKSIZE, "missing USTAR end marker")
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    check(not chunk.strip(b"\0"), "content after archive end marker")
                check(stream.tell() % tarfile.BLOCKSIZE == 0, "invalid archive end padding")
                return
            info = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
            kind = header[156:157]
            check(kind in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE), "unsupported raw USTAR type")
            check(header[257:265] == tarfile.POSIX_MAGIC, "non-USTAR header format")
            name, prefix = text(header[:100]), text(header[345:500])
            name = prefix + "/" + name if prefix else name
            if kind == tarfile.DIRTYPE and name.endswith("/"):
                name = name[:-1]  # Exactly one conventional directory slash.
            check(canonical(name) == info.name, "raw/logical USTAR name mismatch")
            check(info.size >= 0 and (kind != tarfile.DIRTYPE or info.size == 0), "invalid USTAR member size")
            remaining = ((info.size + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE) * tarfile.BLOCKSIZE
            while remaining:
                chunk = stream.read(min(remaining, 1024 * 1024))
                check(chunk, "truncated USTAR member")
                remaining -= len(chunk)


def create(sha, run, provider, rust, out):
    identity(sha, run)
    provider, rust = checked(provider, True), checked(rust, True)
    manifest = validate_provider(provider, sha, run)
    with tempfile.TemporaryDirectory(prefix="yoyopod-bundle-stage-") as temporary:
        stage = checked(temporary, True)
        for name in sorted(provider_files(manifest)):
            copy_regular(provider / name, stage / "providers/modemmanager" / name)
        rows = []
        for name in BINARY_PATHS:
            copy_regular(rust / name, stage / name)
            rows.append({"file": name, "sha256": package.digest(stage / name)})
        package.write_json(stage / "manifest.json", {
            "schema_version": 1, "repo_sha": sha, "ci_run_id": run, "binaries": rows,
            "provider_manifest_sha256": package.digest(stage / "providers/modemmanager/manifest.json"),
        })
        files = {"manifest.json", *BINARY_PATHS,
                 *("providers/modemmanager/" + name for name in provider_files(manifest))}
        # Add only the selected regular files and their canonical parent entries.
        # Never recurse into input trees or copy unmanifested output files.
        with tarfile.open(out, "x:gz", format=tarfile.USTAR_FORMAT) as archive:
            for name in sorted(directories(files)):
                info = tarfile.TarInfo(name)
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(info)
            for name in sorted(files):
                path = checked(stage / name)
                info = tarfile.TarInfo(name)
                info.size, info.mode = path.stat().st_size, stat.S_IMODE(path.stat().st_mode)
                with path.open("rb") as stream:
                    archive.addfile(info, stream)


def verify(path, sha, run):
    identity(sha, run)
    path = checked(path)
    raw_ustar(path)
    with tarfile.open(path, "r:gz") as archive, tempfile.TemporaryDirectory(prefix="yoyopod-bundle-verify-") as temporary:
        files, dirs, seen = {}, set(), set()
        for member in archive.getmembers():
            name = canonical(member.name)
            check(name not in seen and not member.pax_headers, "duplicate/extended archive member")
            seen.add(name)
            check(member.mode & 0o7000 == 0, "special archive permissions")
            if member.type == tarfile.DIRTYPE:
                dirs.add(name)
            else:
                check(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE), "non-regular archive member")
                files[name] = member
        # Tar readers stop at an end marker. Reject hidden concatenated members
        # or nonzero trailing content rather than silently ignoring that suffix.
        archive.fileobj.seek(archive.offset)
        padding = 0
        for chunk in iter(lambda: archive.fileobj.read(1024 * 1024), b""):
            check(not chunk.strip(b"\0"), "content after archive end marker")
            padding += len(chunk)
        check(padding >= 1024 and (archive.offset + padding) % 512 == 0, "invalid archive end padding")

        def read(name):
            check(name in files, "missing archive file: " + name)
            with archive.extractfile(files[name]) as stream:
                return stream.read()

        root = read_json(read("manifest.json"))
        package.exact(root, ("schema_version", "repo_sha", "ci_run_id", "binaries", "provider_manifest_sha256"))
        check(type(root["schema_version"]) is int and root["schema_version"] == 1, "bundle schema version")
        check((root["repo_sha"], root["ci_run_id"]) == (sha, run), "bundle SHA/run mismatch")
        rows = root["binaries"]
        check(isinstance(rows, list) and len(rows) == len(BINARY_PATHS), "binary count")
        for name, row in zip(BINARY_PATHS, rows):
            package.exact(row, ("file", "sha256"))
            check(row["file"] == name and isinstance(row["sha256"], str)
                  and re.fullmatch(package.DIGEST, row["sha256"]) is not None, "binary path/order/hash")
            check(hashlib.sha256(read(name)).hexdigest() == row["sha256"], "binary byte mismatch")
        inner_bytes = read("providers/modemmanager/manifest.json")
        check(isinstance(root["provider_manifest_sha256"], str)
              and hashlib.sha256(inner_bytes).hexdigest() == root["provider_manifest_sha256"],
              "raw provider manifest mismatch")
        inner = read_json(inner_bytes)
        names = provider_files(inner)
        expected = {"manifest.json", *BINARY_PATHS,
                    *("providers/modemmanager/" + name for name in names)}
        check(set(files) == expected, "extra/missing archive file")
        check(dirs <= directories(expected), "extra archive directory")
        # All archive names/types/membership have been checked before any write.
        # Selected files are streamed into new regular files, never tar-extracted.
        destination = checked(temporary, True)
        for name in sorted(names):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(files["providers/modemmanager/" + name]) as stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output)
        validate_provider(destination, sha, run)


def publish(source, destination):
    source = checked(source)
    raw = Path(destination)
    check(".." not in raw.parts and raw.name not in ("", "."), "invalid output path")
    target = checked(raw.parent, True) / raw.name
    created = False
    try:
        with target.open("xb") as output:
            created = True
            with source.open("rb") as stream:
                shutil.copyfileobj(stream, output)
    except BaseException:
        if created:
            target.unlink()
        raise


try:
    action, *arguments = sys.argv[2:]
    {"create": create, "verify": verify, "publish": publish}[action](*arguments)
except (ValueError, TypeError, KeyError, OSError, tarfile.TarError, subprocess.CalledProcessError) as error:
    sys.exit("provider bundle rejected: " + str(error))
PY
}

bundle_verify() (
  set -euo pipefail
  [[ $# == 3 ]] || { echo 'bundle_verify requires TAR SHA RUN' >&2; exit 2; }
  bundle_python verify "$@"
)

bundle_main() (
  set -euo pipefail
  local sha='' run='' provider='' rust='' out='' option value repo work
  declare -A supplied=()
  while [[ $# -gt 0 ]]; do
    [[ $# -ge 2 ]] || { echo 'missing bundle option value' >&2; exit 2; }
    option=$1; value=$2; shift 2
    [[ -z ${supplied[$option]+present} ]] || { echo 'duplicate bundle option' >&2; exit 2; }
    supplied[$option]=1
    case "$option" in
      --repo-sha) sha=$value ;;
      --ci-run-id) run=$value ;;
      --provider) provider=$value ;;
      --rust-root) rust=$value ;;
      --out) out=$value ;;
      *) echo 'unknown bundle option' >&2; exit 2 ;;
    esac
  done
  [[ -n "$sha" && -n "$run" && -n "$provider" && -n "$rust" && -n "$out" ]] || {
    echo 'usage: bundle.sh --repo-sha SHA --ci-run-id RUN --provider DIR --rust-root DIR --out TAR' >&2; exit 2;
  }
  repo=$(git -C "$(dirname -- "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
  [[ "$(git -C "$repo" rev-parse HEAD)" == "$sha" ]] || { echo 'checkout/SHA mismatch' >&2; exit 1; }
  work=$(mktemp -d)
  trap 'rm -rf -- "$work"' EXIT
  bundle_python create "$sha" "$run" "$provider" "$rust" "$work/bundle.tar.gz"
  bundle_verify "$work/bundle.tar.gz" "$sha" "$run"
  bundle_python publish "$work/bundle.tar.gz" "$out"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  bundle_main "$@"
fi
