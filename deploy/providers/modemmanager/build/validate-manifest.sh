#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 ]] || exit 2
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
jq -e '
  def exact($expected): type == "object" and keys == ($expected|sort);
  def digest: type == "string" and test("^[0-9a-f]{64}$");
  def file: type == "string" and length > 0
    and (explode|all(. >= 32 and . != 127 and . != 92 and . != 58))
    and (split("/")|all(. != "" and . != "." and . != ".."));
  exact(["schema_version","repo_sha","ci_run_id","source_version","package_version","architecture",
    "source_lock_sha256","patch_series_sha256","profile_sha256","daemon_sha256","packages","source_files","reports"])
  and .schema_version == 1 and (.repo_sha|type == "string" and test("^[0-9a-f]{40}$"))
  and (.ci_run_id|type == "string" and test("^[0-9]+$"))
  and .source_version == "1.24.0-1+deb13u1" and .package_version == "1.24.0-1+deb13u1+yoyopod1"
  and .architecture == "arm64"
  and (.source_lock_sha256|digest) and (.patch_series_sha256|digest)
  and (.profile_sha256|digest) and (.daemon_sha256|digest)
  and (.packages|type == "array" and length > 0 and all(.[];
    exact(["file","sha256","name","version","architecture"]) and (.file|file) and (.sha256|digest)
    and (.name|type == "string" and test("^[a-z0-9][a-z0-9+.-]+$"))
    and (.version|type == "string" and length > 0) and (.architecture == "arm64" or .architecture == "all")))
  and all(.source_files,.reports; type == "array" and length > 0 and all(.[];
    exact(["file","sha256"]) and (.file|file) and (.sha256|digest)))
' "$1/manifest.json" >/dev/null
# Strict duplicate-key parsing, actual hashes, unknown profile fields, file
# confinement/symlinks and whole-tree membership are checked against real bytes.
python3 "$root/build/package.py" validate "$1"
