#!/usr/bin/env python3
"""Off-device contract tests; fixtures are explicitly synthetic package bytes."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("packaging", ROOT / "build/package.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)

class PackagingTests(unittest.TestCase):
    def bundle(self, path):
        for directory in ("source/patches", "packages", "reports"):
            (path / directory).mkdir(parents=True, exist_ok=True)
        (path / "profile.json").write_bytes((ROOT / "profile.json").read_bytes())
        (path / "source/source-lock.json").write_bytes((ROOT / "source-lock.json").read_bytes())
        (path / "source/patches/series").write_text("synthetic-fixture-series\n")
        records = []
        for name in ("modemmanager", "libmm-glib0"):
            file = path / "packages" / (name + ".deb")
            file.write_bytes(b"SYNTHETIC PACKAGE FIXTURE; NOT A DEBIAN ARCHIVE")
            records.append({"name": name, "version": packaging.VERSION, "architecture": "arm64",
                            "file": file.relative_to(path).as_posix(), "sha256": packaging.digest(file)})
        packaging.write_json(path / "reports/dependency-closure.json", {"packages": records})
        packaging.manifest(path, "a" * 40, "123", "b" * 64)
        return path

    def test_actual_manifest_hash_and_unknown_field_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.bundle(Path(tmp))
            self.assertEqual(packaging.validate_manifest(root)["ci_run_id"], "123")
            manifest = json.loads((root / "manifest.json").read_text())
            manifest["unexpected"] = True
            packaging.write_json(root / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "unknown/missing"):
                packaging.validate_manifest(root)
            del manifest["unexpected"]
            packaging.write_json(root / "manifest.json", manifest)
            (root / "packages/modemmanager.deb").write_bytes(b"TAMPERED SYNTHETIC PAYLOAD")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                packaging.validate_manifest(root)

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.bundle(Path(tmp))
            file = root / "manifest.json"
            text = file.read_text().replace('"ci_run_id": "123",', '"ci_run_id": "999", "ci_run_id": "123",')
            file.write_text(text)
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                packaging.validate_manifest(root)

    def test_real_comparison_rejects_changed_source_and_preserves_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            first, second = self.bundle(parent / "first"), self.bundle(parent / "second")
            report = parent / "comparison.json"
            packaging.compare(first, second, report)
            self.assertTrue(json.loads(report.read_text())["payloads_match"])
            (second / "source/patches/series").write_text("changed synthetic series\n")
            packaging.manifest(second, "a" * 40, "123", "b" * 64)
            with self.assertRaisesRegex(ValueError, "reproducibility mismatch"):
                packaging.compare(first, second, report)
            result = json.loads(report.read_text())
            self.assertFalse(result["payloads_match"])
            self.assertFalse(result["identities_match"])

    def test_dependency_version_requires_nonempty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.bundle(Path(tmp))
            file = root / "packages/dependency.deb"
            file.write_bytes(b"SYNTHETIC DEPENDENCY FIXTURE")
            manifest = packaging.read_json(root / "manifest.json")
            record = {"file": "packages/dependency.deb", "sha256": packaging.digest(file),
                      "name": "dependency", "architecture": "arm64", "version": "1.0"}
            manifest["packages"].append(record)
            packaging.write_json(root / "manifest.json", manifest)
            packaging.validate_manifest(root)
            for version in (True, 42, ["1.0"], {"version": "1.0"}, ""):
                record["version"] = version
                packaging.write_json(root / "manifest.json", manifest)
                with self.subTest(version=version), self.assertRaisesRegex(ValueError, "invalid package identity"):
                    packaging.validate_manifest(root)

    def test_pending_profile(self):
        profile = json.loads((ROOT / "profile.json").read_text())
        packaging.validate_profile(profile)
        profile["qualification"] = "qualified"
        with self.assertRaises(ValueError):
            packaging.validate_profile(profile)

    def test_confined_regular_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "payload").write_bytes(b"synthetic")
            self.assertEqual(packaging.safe_file(root, "payload"), (root / "payload").resolve())
            for name in ("../payload", "/payload", "a/../payload", "a//b", "C:/payload", "a\\b", ".", ""):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    packaging.safe_file(root, name)
            with self.assertRaises(ValueError):
                packaging.safe_file(root, "missing")
            (root / "directory").mkdir()
            with self.assertRaises(ValueError):
                packaging.safe_file(root, "directory")
            try:
                (root / "link").symlink_to(root / "payload")
            except OSError:
                if os.name != "nt":
                    raise
                self.skipTest("host does not allow symlink creation; native test required")
            with self.assertRaises(ValueError):
                packaging.safe_file(root, "link")

    def test_payload_comparison_is_not_provenance_comparison(self):
        first = {"packages": [{"file": "p.deb", "sha256": "a" * 64}],
                 "source_files": [{"file": "s.tar.xz", "sha256": "b" * 64}],
                 "reports": [{"file": "run.buildinfo", "sha256": "c" * 64}]}
        second = json.loads(json.dumps(first))
        second["reports"][0]["sha256"] = "d" * 64
        result = packaging.compare_payloads(first, second)
        self.assertTrue(result["payloads_match"])
        self.assertFalse(result["reports_match"])
        second["packages"][0]["sha256"] = "e" * 64
        self.assertFalse(packaging.compare_payloads(first, second)["payloads_match"])
        second = json.loads(json.dumps(first))
        second["source_files"].append({"file": "unexpected", "sha256": "f" * 64})
        self.assertFalse(packaging.compare_payloads(first, second)["payloads_match"])

    def test_dependency_graph_excludes_unrelated_build_tools(self):
        daemon = {"Package": "modemmanager", "Version": "1", "Depends": "runtime | alternative"}
        runtime = {"Package": "runtime", "Version": "1", "Pre-Depends": "base"}
        base = {"Package": "base", "Version": "1"}
        compiler = {"Package": "gcc", "Version": "14"}
        selected, edges = packaging.select_closure([daemon], [daemon, runtime, base, compiler])
        self.assertEqual([row["Package"] for row in selected], ["base", "modemmanager", "runtime"])
        self.assertEqual(len(edges), 2)
        with self.assertRaisesRegex(ValueError, "NEEDS_CONTEXT"):
            packaging.select_closure([daemon], [daemon, compiler])

    def test_candidate_profile_rejects_boolean_rate(self):
        profile = json.loads((ROOT / "profile.json").read_text())
        profile["contract_revision"] = True
        with self.assertRaises(ValueError):
            packaging.validate_profile(profile)

    def test_control_character_paths_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # A newline is a legal POSIX filename but cannot enter a manifest.
            with self.assertRaises(ValueError):
                packaging.safe_file(root, "bad\nname")

    def test_unknown_profile_fields_and_identity_rejected(self):
        profile = json.loads((ROOT / "profile.json").read_text())
        for key, value in (("unexpected", True), ("evidence", [{}]), ("qmi_primary_type", 1)):
            changed = dict(profile, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                packaging.validate_profile(changed)

if __name__ == "__main__":
    unittest.main()
