#!/usr/bin/env python3
"""Collect stopped-container evidence into a fresh, host-only upload tree.

Only fixed selected paths are read. Check every ancestor, directory and file;
open leaves without following links. Containers must have exited before use.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


def checked(path, kind=None, missing=False):
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        if any(ord(char) < 32 or ord(char) == 127 for char in part):
            raise ValueError("control character in evidence path")
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if missing:
                return None
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("symlink/reparse point in evidence path")
        if current != path or kind == "directory":
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("non-directory evidence component")
        elif not stat.S_ISREG(info.st_mode):
            raise ValueError("non-regular evidence file")
    return path


def regular_files(directory):
    directory = checked(directory, "directory", missing=True)
    if directory is None:
        return []
    result = []
    for entry in sorted(directory.iterdir()):
        info = entry.lstat()
        # Check links before any type operation that might follow them.
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("symlink/reparse point in evidence tree")
        if stat.S_ISDIR(info.st_mode):
            result.extend(regular_files(entry))
        else:
            result.append(checked(entry))
    return result


def read_file(path, destination=None):
    path = checked(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("non-regular opened evidence")
        output = None
        try:
            if destination is not None:
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                checked(destination.parent, "directory")
                output = destination.open("xb")
            sha = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                sha.update(chunk)
                if output:
                    output.write(chunk)
            return sha.hexdigest()
        finally:
            if output:
                output.close()


def collect(evidence, destination, success=False):
    evidence, destination = map(lambda p: Path(os.path.abspath(p)), (evidence, destination))
    if destination == evidence or destination.is_relative_to(evidence) or evidence.is_relative_to(destination):
        raise ValueError("upload destination must be separate from container evidence")
    checked(destination.parent, "directory")
    destination.mkdir(mode=0o700)  # Exclusive creation; never trust/reuse old output.
    diagnostics = destination / "diagnostics"
    diagnostics.mkdir(mode=0o700)
    try:
        checked(evidence, "directory")
        selected, hashes = [], {}
        for build in ("first", "second"):
            base = checked(evidence / build, "directory", missing=True)
            if base is None:
                continue
            for relative in ("execution.log", "bootstrap.log", "output/manifest.json"):
                path = checked(base / relative, missing=True)
                if path:
                    selected.append((path, diagnostics / build / Path(relative).name))
            reports = checked(base / "output/reports", "directory", missing=True)
            if reports:
                for path in regular_files(reports):
                    if path.parent == reports and path.suffix in (".log", ".txt", ".json"):
                        selected.append((path, diagnostics / build / path.name))
            output = checked(base / "output", "directory", missing=True)
            if output:
                hashes[build] = regular_files(output)
        for relative in ("first.json", "second.json", "collector-tests.log"):
            path = checked(evidence / "diagnostics" / relative, missing=True)
            if path:
                selected.append((path, diagnostics / relative))
        for relative in ("second/comparison.log", "second/output.comparison.json"):
            path = checked(evidence / relative, missing=True)
            if path:
                selected.append((path, diagnostics / Path(relative).name))
        # Validate all selected trees before reading any evidence bytes.
        images = regular_files(evidence / "images") if success else []
        for source, target in selected:
            read_file(source, target)
        for build, paths in hashes.items():
            listing = [read_file(path) + "  " + path.relative_to(evidence / build / "output").as_posix()
                       for path in paths]
            target = diagnostics / build / "output-sha256.txt"
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_text("\n".join(listing) + "\n", encoding="utf-8")
        if success:
            # Independently enforce actual-byte equality before materializing any
            # uploadable package/source payloads in the protected destination.
            spec = importlib.util.spec_from_file_location("provider_package", Path(__file__).with_name("package.py"))
            package = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(package)
            package.compare(evidence / "first/output", evidence / "second/output",
                            diagnostics / "host-comparison.json")
            for path in hashes["first"]:
                read_file(path, destination / "candidate" / path.relative_to(evidence / "first/output"))
            for path in images:
                read_file(path, destination / "images" / path.relative_to(evidence / "images"))
        (diagnostics / "collection.json").write_text(json.dumps({"schema_version": 1, "accepted": True,
                                                                "candidate_materialized": success}) + "\n")
    except Exception as error:
        # An exception never authorizes the success uploader. This file contains
        # only our error classification, not bytes read from an unsafe source.
        (diagnostics / "collection.json").write_text(json.dumps({"schema_version": 1, "accepted": False,
                                                                "error_type": type(error).__name__}) + "\n")
        raise


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[3] not in ("success", "failure"):
        sys.exit("usage: collect-evidence.py EVIDENCE FRESH_DEST success|failure")
    try:
        collect(sys.argv[1], sys.argv[2], sys.argv[3] == "success")
    except (ValueError, OSError, KeyError) as error:
        sys.exit("evidence collection rejected: " + str(error))
