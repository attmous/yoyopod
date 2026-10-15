#!/usr/bin/env python3
"""Fixed off-device packaging helpers; only Python's locked standard library."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

DIGEST = r"[0-9a-f]{64}"
VERSION = "1.24.0-1+deb13u1+yoyopod1"


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        result = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_file(root, name):
    check(isinstance(name, str) and name and "\\" not in name and ":" not in name
          and not any(ord(char) < 32 or ord(char) == 127 for char in name),
          "invalid relative file")
    parts = name.split("/")
    check(all(part not in ("", ".", "..") for part in parts), "noncanonical file path")
    check(not PurePosixPath(name).is_absolute(), "absolute file path")
    root = Path(root).resolve(strict=True)
    current = root
    for part in parts:
        current /= part
        check(not current.is_symlink(), "symlink in manifest path")
    check(current.is_file() and current.resolve().is_relative_to(root), "not a confined regular file")
    return current


def validate_profile(profile):
    expected = {"schema_version": 1,
                "profile_id": "sim7600g-h-le20b04sim7600g22-simtech-pcm-v1",
                "qualification": "qualification_pending",
                "modem": {"manufacturer": "QUALCOMM INCORPORATED", "model": "SIMCOM_SIM7600G-H",
                          "revision": "LE20B04SIM7600G22", "hardware_revision": "10000", "plugin": "simtech"},
                "qmi_primary_type": 6,
                "format": {"encoding": "pcm", "resolution": "s16le", "rate": 16000, "channels": 1},
                "contract_revision": 1, "evidence": []}
    # Compare JSON encodings too: Python considers True equal to 1.
    check(json.dumps(profile, sort_keys=True) == json.dumps(expected, sort_keys=True),
          "candidate profile fields/identity/status mismatch; qualification needs separate review")


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            check(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def exact(obj, keys):
    check(isinstance(obj, dict) and set(obj) == set(keys), "unknown/missing object fields")


def validate_manifest(root):
    root = Path(root)
    manifest = read_json(safe_file(root, "manifest.json"))
    exact(manifest, ["schema_version", "repo_sha", "ci_run_id", "source_version", "package_version",
                     "architecture", "source_lock_sha256", "patch_series_sha256", "profile_sha256",
                     "daemon_sha256", "packages", "source_files", "reports"])
    check(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1, "schema version")
    check(re.fullmatch(r"[0-9a-f]{40}", manifest["repo_sha"]) is not None, "repo SHA")
    check(re.fullmatch(r"[0-9]+", manifest["ci_run_id"]) is not None, "CI run")
    check(manifest["architecture"] == "arm64" and manifest["package_version"] == VERSION and
          manifest["source_version"] == "1.24.0-1+deb13u1", "provider identity")
    for field in ("source_lock_sha256", "patch_series_sha256", "profile_sha256", "daemon_sha256"):
        check(re.fullmatch(DIGEST, manifest[field]) is not None, "invalid digest")
    seen = {"manifest.json", "profile.json"}
    names = set()
    for kind in ("packages", "source_files", "reports"):
        check(isinstance(manifest[kind], list) and manifest[kind], "empty manifest section")
        for item in manifest[kind]:
            exact(item, ["file", "sha256", "name", "version", "architecture"] if kind == "packages" else ["file", "sha256"])
            check(item["file"] not in seen, "duplicate manifest path")
            seen.add(item["file"])
            check(re.fullmatch(DIGEST, item["sha256"]) is not None, "invalid file digest")
            check(digest(safe_file(root, item["file"])) == item["sha256"], "file hash mismatch")
            if kind == "packages":
                check(item["architecture"] in ("arm64", "all") and
                      isinstance(item["version"], str) and item["version"] and
                      re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", item["name"]), "invalid package identity")
                check(item["name"] not in names, "duplicate package name")
                names.add(item["name"])
    check({"modemmanager", "libmm-glib0"} <= names, "missing candidate runtime package")
    check(all(item["version"] == VERSION for item in manifest["packages"]
              if item["name"] in ("modemmanager", "libmm-glib0")), "candidate package version")
    check(digest(safe_file(root, "profile.json")) == manifest["profile_sha256"], "profile hash mismatch")
    validate_profile(read_json(root / "profile.json"))
    for field, name in (("source_lock_sha256", "source/source-lock.json"),
                        ("patch_series_sha256", "source/patches/series")):
        check(digest(safe_file(root, name)) == manifest[field], "input binding mismatch")
    # No unmanifested archives, dangling links, or special files can enter a bundle.
    actual = set()
    for path in root.rglob("*"):
        check(not path.is_symlink(), "symlink in output tree")
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        safe_file(root, name)
        actual.add(name)
    check(actual == seen, "unmanifested/missing output file")
    return manifest


def compare_payloads(first, second):
    def files(value, key):
        return {item["file"]: item["sha256"] for item in value[key]}
    return {"payloads_match": all(files(first, key) == files(second, key)
                                  for key in ("packages", "source_files")),
            "reports_match": files(first, "reports") == files(second, "reports")}


def compare(first, second, destination):
    left, right = validate_manifest(first), validate_manifest(second)
    identity = ("repo_sha", "ci_run_id", "source_version", "package_version", "architecture",
                "source_lock_sha256", "patch_series_sha256", "profile_sha256", "daemon_sha256")
    result = compare_payloads(left, right)
    result.update(schema_version=1, first_manifest_sha256=digest(Path(first) / "manifest.json"),
                  second_manifest_sha256=digest(Path(second) / "manifest.json"),
                  identities_match=all(left[key] == right[key] for key in identity),
                  report_differences=[name for name in sorted({x["file"] for x in left["reports"] + right["reports"]})
                                      if next((x["sha256"] for x in left["reports"] if x["file"] == name), None) !=
                                      next((x["sha256"] for x in right["reports"] if x["file"] == name), None)])
    write_json(destination, result)
    check(result["identities_match"] and result["payloads_match"], "package/source reproducibility mismatch")


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def deb822(text):
    records, record, key = [], {}, None
    for line in text.splitlines() + [""]:
        if not line:
            if record:
                records.append(record)
            record, key = {}, None
        elif line[0].isspace():
            check(key is not None, "invalid Debian continuation")
            record[key] += "\n" + line[1:]
        else:
            key, value = line.split(":", 1)
            check(key not in record, "duplicate Debian control field")
            record[key] = value.lstrip()
    return records


def relation_groups(value):
    groups = []
    for group in value.replace("\n", " ").split(","):
        if not group.strip():
            continue
        alternatives = []
        for part in group.split("|"):
            match = re.fullmatch(r"\s*([a-z0-9][a-z0-9+.-]+)(?::(any|native|arm64))?\s*(?:\((<<|<=|=|>=|>>)\s*([^()\s]+)\))?\s*", part)
            check(match is not None, "unsupported dependency relation: " + part)
            name, arch, operator, version = match.groups()
            alternatives.append((name, operator, version))
        groups.append(alternatives)
    return groups


def satisfies(record, relation):
    name, operator, version = relation
    candidates = []
    if record["Package"] == name:
        candidates.append(record["Version"])
    for alternatives in relation_groups(record.get("Provides", "")):
        for provided, op, provided_version in alternatives:
            if provided == name:
                candidates.append(provided_version if op == "=" else None)
    return any(not operator or (candidate and subprocess.run(
        ["dpkg", "--compare-versions", candidate, operator, version], check=False).returncode == 0)
               for candidate in candidates)


def select_closure(roots, available):
    selected, queue, edges = {}, list(roots), []
    while queue:
        record = queue.pop(0)
        previous = selected.get(record["Package"])
        if previous:
            check(previous["Version"] == record["Version"], "conflicting dependency version")
            continue
        selected[record["Package"]] = record
        for field in ("Pre-Depends", "Depends"):
            for group in relation_groups(record.get(field, "")):
                choice = next((candidate for relation in group for candidate in available
                               if satisfies(candidate, relation)), None)
                check(choice is not None, "NEEDS_CONTEXT: dependency absent from locked closure: " + str(group))
                edges.append({"from": record["Package"], "field": field, "relation": group,
                              "selected": choice["Package"], "version": choice["Version"]})
                queue.append(choice)
    return sorted(selected.values(), key=lambda record: record["Package"]), edges


def fetch(url, destination, expected):
    check(url.startswith("https://snapshot.debian.org/archive/debian/"), "non-snapshot download")
    subprocess.run(["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
                    "--retry", "3", "--connect-timeout", "30", "--max-time", "600", url,
                    "-o", str(destination)], check=True)
    check(digest(destination) == expected, "signed archive hash mismatch")


def closure(lock_path, cache_path, build_path, out_path):
    lock = read_json(lock_path)
    cache, build, out = map(Path, (cache_path, build_path, out_path))
    index = deb822((cache / "metadata/packages.txt").read_text())
    sources = deb822((cache / "metadata/sources.txt").read_text())
    binaries = {}
    for path in sorted(build.glob("*.deb")):
        record = deb822(command("dpkg-deb", "-f", str(path)))[0]
        check(record["Architecture"] in ("arm64", "all") and record["Version"] == VERSION,
              "unexpected produced package")
        binaries[record["Package"]] = (record, path)
    check({"modemmanager", "libmm-glib0"} <= binaries.keys(), "missing runtime outputs")
    pins = {pin["name"]: pin for pin in lock["build_dependencies"]}
    available = [item[0] for item in binaries.values()]
    for record in index:
        pin = pins.get(record["Package"])
        if pin and (record["Version"], record["Architecture"], record["SHA256"]) == (pin["version"], pin["architecture"], pin["sha256"]):
            if record["Package"] not in binaries:
                available.append(record)
    chosen, edges = select_closure([binaries[name][0] for name in ("modemmanager", "libmm-glib0")], available)
    base = "https://snapshot.debian.org/archive/debian/" + lock["snapshot"] + "/"
    source_seen, source_records, package_records = set(), [], []
    extracted = cache / "license-extract"
    extracted.mkdir()
    for record in chosen:
        name = record["Package"]
        if name in binaries:
            path = binaries[name][1]
        else:
            filename = record["Filename"]
            check(filename.startswith("pool/") and ".." not in filename.split("/"), "invalid signed package path")
            path = cache / "downloads" / Path(filename).name
            check(path.is_file() and digest(path) == record["SHA256"], "verified binary cache mismatch")
            # The produced package's actual control records drive the graph; bind
            # each selected distribution record back to its real archive too.
            actual = deb822(command("dpkg-deb", "-f", str(path)))[0]
            for key in ("Package", "Version", "Architecture", "Depends", "Pre-Depends", "Provides"):
                check(actual.get(key, "") == record.get(key, ""), "binary control/index mismatch: " + key)
        target = out / "packages" / path.name
        shutil.copyfile(path, target)
        package_records.append({"file": target.relative_to(out).as_posix(), "name": name,
                                "version": record["Version"], "architecture": record["Architecture"],
                                "sha256": digest(target)})
        subprocess.run(["dpkg-deb", "-x", str(path), str(extracted)], check=True)
        if name in binaries:
            continue
        source_match = re.fullmatch(r"([^ ()]+)(?: \(([^()]+)\))?", record.get("Source", name))
        check(source_match is not None, "invalid source identity")
        source_name, source_version = source_match.groups()
        source_version = source_version or record["Version"]
        identity = (source_name, source_version)
        if identity in source_seen:
            continue
        source_seen.add(identity)
        matches = [source for source in sources if source["Package"] == source_name and source["Version"] == source_version]
        check(len(matches) == 1, "NEEDS_CONTEXT: corresponding source absent from signed Sources: " + str(identity))
        source = matches[0]
        directory = source["Directory"]
        check(directory.startswith("pool/") and ".." not in directory.split("/"), "invalid signed source directory")
        for line in source["Checksums-Sha256"].splitlines():
            if not line.strip():
                continue
            expected, size, filename = line.split()
            check(re.fullmatch(DIGEST, expected) and Path(filename).name == filename and "/" not in filename,
                  "invalid signed source file")
            destination = out / "source/dependencies" / filename
            if destination.exists():
                check(digest(destination) == expected, "source filename collision")
            else:
                fetch(base + directory + "/" + filename, destination, expected)
            check(destination.stat().st_size == int(size), "source size mismatch")
            source_records.append({"source": source_name, "version": source_version,
                                   "file": destination.relative_to(out).as_posix(), "sha256": expected,
                                   "request_uri": base + directory + "/" + filename})
    for record in chosen:
        name = record["Package"]
        copyright_path = extracted / "usr/share/doc" / name / "copyright"
        resolved = copyright_path.resolve(strict=True)
        check(resolved.is_relative_to(extracted.resolve()) and resolved.is_file(), "copyright not confined")
        shutil.copyfile(resolved, out / "source/licenses" / (name + ".copyright"))
    write_json(out / "reports/dependency-closure.json", {"schema_version": 1, "roots": ["modemmanager", "libmm-glib0"],
               "edges": edges, "packages": package_records, "corresponding_sources": source_records,
               "signed_packages_sha256": digest(cache / "metadata/packages"),
               "signed_sources_sha256": digest(cache / "metadata/sources")})
    return package_records


def manifest(out_path, sha, run, daemon_hash):
    out = Path(out_path)
    lock = read_json(out / "source/source-lock.json")
    def entries(directory):
        return [{"file": path.relative_to(out).as_posix(), "sha256": digest(path)}
                for path in sorted((out / directory).rglob("*")) if path.is_file()]
    value = {"schema_version": 1, "repo_sha": sha, "ci_run_id": run,
             "source_version": lock["source_version"], "package_version": lock["package_version"],
             "architecture": lock["architecture"], "source_lock_sha256": digest(out / "source/source-lock.json"),
             "patch_series_sha256": digest(out / "source/patches/series"),
             "profile_sha256": digest(out / "profile.json"), "daemon_sha256": daemon_hash,
             "packages": read_json(out / "reports/dependency-closure.json")["packages"],
             "source_files": entries("source"), "reports": entries("reports")}
    write_json(out / "manifest.json", value)
    validate_manifest(out)


if __name__ == "__main__":
    try:
        action, *args = sys.argv[1:]
        {"validate": validate_manifest, "compare": compare, "closure": closure, "manifest": manifest}[action](*args)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        sys.exit("provider packaging: " + str(error))
