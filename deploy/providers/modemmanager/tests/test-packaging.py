#!/usr/bin/env python3
"""Off-device contract tests; fixtures are explicitly synthetic package bytes."""
import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("packaging", ROOT / "build/package.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)

class PackagingTests(unittest.TestCase):
    @staticmethod
    def pending_profile():
        # Synthetic status is independent of any future reviewed real promotion.
        profile = json.loads((ROOT / "profile.json").read_text())
        profile.update(qualification="qualification_pending", evidence=[])
        return profile

    def bundle(self, path):
        for directory in ("source/patches", "packages", "reports"):
            (path / directory).mkdir(parents=True, exist_ok=True)
        packaging.write_json(path / "profile.json", self.pending_profile())
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

    def qualification_fixture(self, parent):
        output = self.bundle(parent / "output")
        binding = packaging.provider_inputs_sha256(output)
        checkout = parent / "checkout"
        evidence = checkout / "qualification/synthetic.md"
        evidence.parent.mkdir(parents=True)
        evidence.write_bytes(b"SYNTHETIC SOFTWARE FIXTURE: NO HARDWARE QUALIFICATION")
        profile = self.pending_profile()
        profile["qualification"] = "qualified"
        profile["evidence"] = [
            {"kind": kind, "path": "source/qualification/synthetic.md",
             "sha256": packaging.digest(evidence), "modem": dict(profile["modem"]),
             "provider_inputs_sha256": binding} for kind in ("framing", "lifecycle")]
        packaging.write_json(checkout / "profile.json", profile)
        return output, checkout, profile, binding

    def finish_qualified_fixture(self, output, checkout):
        (output / "profile.json").unlink()
        packaging.stage_profile(checkout, output)
        packaging.manifest(output, "a" * 40, "123", "b" * 64)

    def test_qualified_profile_complete_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, checkout, profile, binding = self.qualification_fixture(Path(tmp))
            self.finish_qualified_fixture(output, checkout)
            actual = packaging.validate_manifest(output)
            self.assertEqual(actual["profile_sha256"], packaging.digest(output / "profile.json"))
            self.assertEqual(packaging.provider_inputs_sha256(output), binding)
            packaging.validate_profile(profile, output)
            with self.assertRaisesRegex(ValueError, "completed output context"):
                packaging.validate_profile(profile)
            changed = json.loads(json.dumps(profile))
            changed["evidence"].reverse()
            with self.assertRaisesRegex(ValueError, "differs from validated output"):
                packaging.validate_profile(changed, output)
            staged = output / "source/qualification/synthetic.md"
            self.assertEqual(staged.read_bytes(), (checkout / "qualification/synthetic.md").read_bytes())
            self.assertEqual(len(list(staged.parent.iterdir())), 1)

    def test_pending_profile_staging_needs_no_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkout, output = root / "checkout", root / "output"
            checkout.mkdir(); output.mkdir()
            packaging.write_json(checkout / "profile.json", self.pending_profile())
            packaging.stage_profile(checkout, output)
            self.assertFalse((output / "source/qualification").exists())
            self.assertEqual((output / "profile.json").read_bytes(), (checkout / "profile.json").read_bytes())

    def test_qualification_record_structure_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            _, checkout, profile, _ = self.qualification_fixture(parent)
            changes = [
                ("bare", lambda p: p.update(evidence=[])),
                ("missing-kind", lambda p: p["evidence"].pop()),
                ("duplicate-kind", lambda p: p["evidence"][1].update(kind="framing")),
                ("unknown-field", lambda p: p["evidence"][0].update(extra=True)),
                ("missing-field", lambda p: p["evidence"][0].pop("sha256")),
                ("wrong-modem", lambda p: p["evidence"][0]["modem"].update(hardware_revision=10000)),
                ("unknown-modem-field", lambda p: p["evidence"][0]["modem"].update(extra=True)),
                ("wrong-profile-type", lambda p: p.update(contract_revision=True)),
                ("pending-with-evidence", lambda p: p.update(qualification="qualification_pending")),
            ]
            for field in ("sha256", "provider_inputs_sha256"):
                for value in (True, 42, [], {}, "A" * 64, "abc"):
                    changes.append((field + repr(value), lambda p, f=field, v=value: p["evidence"][0].update({f: v})))
            for name in ("../x", "/source/qualification/x", "source/qualification/../x",
                         "source/qualification//x", "source/qualification/./x", "source/qualification/",
                         "source/qualification/x\\y", "source/qualification/C:x", "source/qualification/x\ny",
                         "source/other/x", "qualification/x"):
                changes.append((name, lambda p, n=name: p["evidence"][0].update(path=n)))
            for index, (name, change) in enumerate(changes):
                bad = json.loads(json.dumps(profile)); change(bad)
                packaging.write_json(checkout / "profile.json", bad)
                output = parent / ("rejected-" + str(index)); output.mkdir()
                with self.subTest(case=name), self.assertRaises(ValueError):
                    packaging.stage_profile(checkout, output)
                self.assertFalse((output / "profile.json").exists())
            packaging.write_json(checkout / "profile.json", profile)
            text = (checkout / "profile.json").read_text().replace('"kind": "framing",', '"kind": "lifecycle", "kind": "framing",')
            (checkout / "profile.json").write_text(text)
            output = parent / "duplicate-key"; output.mkdir()
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                packaging.stage_profile(checkout, output)

    def test_qualification_missing_tampered_and_wrong_binding(self):
        for failure in ("missing", "tampered", "binding"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                output, checkout, profile, _ = self.qualification_fixture(Path(tmp))
                evidence = checkout / "qualification/synthetic.md"
                if failure == "missing":
                    evidence.unlink()
                elif failure == "tampered":
                    evidence.write_bytes(b"TAMPERED SYNTHETIC EVIDENCE")
                else:
                    profile["evidence"][0]["provider_inputs_sha256"] = "0" * 64
                    packaging.write_json(checkout / "profile.json", profile)
                with self.assertRaises(ValueError):
                    self.finish_qualified_fixture(output, checkout)

    def test_evidence_set_and_immutable_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, checkout, profile, binding = self.qualification_fixture(Path(tmp))
            expected = packaging.provider_inputs_sha256(output)
            original_packages = {p.name: p.read_bytes() for p in (output / "packages").iterdir()}
            self.finish_qualified_fixture(output, checkout)
            evidence = output / "source/qualification/synthetic.md"
            evidence.write_bytes(b"UPDATED SYNTHETIC EVIDENCE")
            for record in profile["evidence"]:
                record["sha256"] = packaging.digest(evidence)
            packaging.write_json(output / "profile.json", profile)
            packaging.manifest(output, "c" * 40, "456", "b" * 64)
            self.assertEqual(packaging.provider_inputs_sha256(output), expected)
            self.assertEqual({p.name: p.read_bytes() for p in (output / "packages").iterdir()}, original_packages)
            (evidence.parent / "unreferenced.md").write_bytes(b"UNREFERENCED SYNTHETIC DATA")
            with self.assertRaisesRegex(ValueError, "unreferenced/missing"):
                packaging.manifest(output, "c" * 40, "456", "b" * 64)
            (evidence.parent / "unreferenced.md").unlink()
            packaging.write_json(output / "profile.json", self.pending_profile())
            with self.assertRaisesRegex(ValueError, "unreferenced/missing"):
                packaging.manifest(output, "c" * 40, "456", "b" * 64)
        # Actual validated pending outputs provide the noncircular binding input.
        for mutation in ("source", "patch", "package", "package-identity"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = self.bundle(Path(tmp))
                before = packaging.provider_inputs_sha256(root)
                if mutation == "source":
                    (root / "source/new-source.txt").write_bytes(b"CHANGED SYNTHETIC SOURCE")
                elif mutation == "patch":
                    (root / "source/patches/series").write_text("changed synthetic patch series\n")
                else:
                    records = packaging.read_json(root / "reports/dependency-closure.json")
                    if mutation == "package":
                        file = root / records["packages"][0]["file"]
                        file.write_bytes(b"CHANGED SYNTHETIC PACKAGE")
                        records["packages"][0]["sha256"] = packaging.digest(file)
                    else:
                        records["packages"][0]["architecture"] = "all"
                    packaging.write_json(root / "reports/dependency-closure.json", records)
                packaging.manifest(root, "a" * 40, "123", "b" * 64)
                self.assertNotEqual(packaging.provider_inputs_sha256(root), before)

    def test_qualification_completed_context_tampering(self):
        for failure in ("evidence-hash", "provider-binding", "record-identity", "missing-evidence"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                output, checkout, profile, _ = self.qualification_fixture(Path(tmp))
                self.finish_qualified_fixture(output, checkout)
                if failure == "missing-evidence":
                    (output / "source/qualification/synthetic.md").unlink()
                elif failure == "evidence-hash":
                    (output / "source/qualification/synthetic.md").write_bytes(b"TAMPERED STAGED EVIDENCE")
                elif failure == "provider-binding":
                    profile["evidence"][0]["provider_inputs_sha256"] = "0" * 64
                else:
                    profile["evidence"][0]["modem"]["plugin"] = "other"
                packaging.write_json(output / "profile.json", profile)
                # Re-enumerate the actual changed bytes: stale record bindings
                # must fail even when the ordinary manifest hashes are updated.
                with self.assertRaises(ValueError):
                    packaging.manifest(output, "a" * 40, "123", "b" * 64)
                with self.assertRaises(ValueError):
                    packaging.provider_inputs_sha256(output)

    def test_provider_digest_canonical_encoding(self):
        # Literal reviewed cross-language vector: pure synthetic encoding only,
        # never a production manifest or an admission/qualification shortcut.
        canonical = (
            '{"architecture":"arm64","daemon_sha256":"3333333333333333333333333333333333333333333333333333333'
            '333333333","package_version":"synthetic-package-1","packages":[{"architecture":"arm64","file":"p'
            'ackages/synthetic.deb","name":"synthetic-package","sha256":"444444444444444444444444444444444444'
            '4444444444444444444444444444","version":"1"}],"patch_series_sha256":"222222222222222222222222222'
            '2222222222222222222222222222222222222","source_files":[{"file":"source/a.txt","sha256":"55555555'
            '55555555555555555555555555555555555555555555555555555555"},{"file":"source/fixture-é.txt","sha25'
            '6":"6666666666666666666666666666666666666666666666666666666666666666"}],"source_lock_sha256":"11'
            '11111111111111111111111111111111111111111111111111111111111111","source_version":"synthetic-sour'
            'ce-1"}'
        ).encode("utf-8")
        expected_vector = "21e0c1ab181642a36b457c7e15ee3b78dfec498c3bfe61d38a052f8ce5579f7e"
        self.assertEqual(len(canonical), 775)
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected_vector)
        vector = json.loads(canonical)
        self.assertEqual(packaging._provider_inputs_digest(vector), expected_vector)
        vector["source_files"].reverse()
        vector["source_files"].append({"file": "source/qualification/synthetic.md", "sha256": "7" * 64})
        vector.update(repo_sha="8" * 40, ci_run_id="123", profile_sha256="9" * 64,
                      reports=[{"file": "reports/synthetic.txt", "sha256": "a" * 64}])
        self.assertEqual(packaging._provider_inputs_digest(vector), expected_vector)
        with tempfile.TemporaryDirectory() as tmp:
            root = self.bundle(Path(tmp))
            (root / "source/fixture-\u00e9.txt").write_bytes(b"SYNTHETIC UTF8 PATH")
            packaging.manifest(root, "a" * 40, "123", "b" * 64)
            manifest = packaging.validate_manifest(root)
            expected = packaging.provider_inputs_sha256(root)
            for section in ("packages", "source_files", "reports"):
                manifest[section].reverse()
            manifest.update(repo_sha="c" * 40, ci_run_id="456")
            packaging.write_json(root / "manifest.json", manifest)
            self.assertEqual(packaging.provider_inputs_sha256(root), expected)
            manifest["daemon_sha256"] = "d" * 64
            packaging.write_json(root / "manifest.json", manifest)
            self.assertNotEqual(packaging.provider_inputs_sha256(root), expected)

    def test_qualification_stage_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            probe = parent / "probe-target"; probe.mkdir()
            try:
                (parent / "probe-link").symlink_to(probe, target_is_directory=True)
            except OSError:
                if os.name != "nt":
                    raise
                self.skipTest("Windows symlink privilege absent; native qualification staging test required")
            for side, component in ((s, c) for s in ("source", "destination")
                                    for c in ("root", "parent", "leaf")):
                with self.subTest(side=side, component=component):
                    case = parent / (side + component)
                    output, checkout, _, _ = self.qualification_fixture(case)
                    (output / "profile.json").unlink()
                    tree = checkout if side == "source" else output
                    relative = Path("qualification") if side == "source" else Path("source/qualification")
                    if component == "root":
                        target = case / "linked-root"; target.symlink_to(tree, target_is_directory=True)
                        if side == "source": checkout = target
                        else: output = target
                    elif component == "parent":
                        target = tree / relative
                        if target.exists(): target.rename(tree / "held-evidence")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.symlink_to(probe, target_is_directory=True)
                    else:
                        target = tree / relative / "synthetic.md"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists(): target.unlink()
                        target.symlink_to(probe / "outside.md")
                    with self.assertRaises((ValueError, OSError)):
                        packaging.stage_profile(checkout, output)

    @unittest.skipIf(os.name == "nt", "POSIX FIFO fixture requires native execution")
    def test_qualification_stage_special_file_refusal(self):
        for side, component in ((s, c) for s in ("source", "destination") for c in ("parent", "leaf")):
            with self.subTest(side=side, component=component), tempfile.TemporaryDirectory() as tmp:
                output, checkout, _, _ = self.qualification_fixture(Path(tmp))
                (output / "profile.json").unlink()
                target = (checkout / "qualification" if side == "source"
                          else output / "source/qualification")
                if component == "leaf":
                    target /= "synthetic.md"
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_dir():
                    target.rename(target.parent / "held-evidence")
                elif target.exists():
                    target.unlink()
                os.mkfifo(target)
                with self.assertRaises((ValueError, OSError)):
                    packaging.stage_profile(checkout, output)

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

    def test_actual_shell_manifest_validator(self):
        if os.name == "nt" and not shutil.which("jq"):
            self.skipTest("jq unavailable on Windows; actual shell validation requires native execution")
        self.assertIsNotNone(shutil.which("jq"), "native jq is required")
        validator = ROOT / "build/validate-manifest.sh"
        # Execute the actual jq filter independently so Python cannot mask a
        # weakened exact-key check, then execute the complete shell wrapper.
        query = validator.read_text().split("jq -e '\n", 1)[1].split("\n' ", 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = self.bundle(Path(tmp))
            manifest = packaging.read_json(root / "manifest.json")

            def check_query(value, accepted):
                result = subprocess.run(["jq", "-e", query], input=json.dumps(value),
                                        text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0 if accepted else 1,
                                 result.stdout + result.stderr)

            check_query(manifest, True)
            for location in (None, "packages", "source_files", "reports"):
                for mutation in ("unknown", "missing"):
                    changed = json.loads(json.dumps(manifest))
                    record = changed if location is None else changed[location][0]
                    if mutation == "unknown":
                        record["unexpected"] = True
                    else:
                        del record["ci_run_id" if location is None else "file"]
                    with self.subTest(location=location, mutation=mutation):
                        check_query(changed, False)

            result = subprocess.run(["bash", str(validator), str(root)],
                                    text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # jq accepts duplicate keys, so the wrapper must still reach its
            # strict Python second stage and refuse this otherwise-valid input.
            file = root / "manifest.json"
            file.write_text(file.read_text().replace(
                '"ci_run_id": "123",', '"ci_run_id": "999", "ci_run_id": "123",'))
            result = subprocess.run(["bash", str(validator), str(root)],
                                    text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate JSON", result.stderr)

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
        profile = self.pending_profile()
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
        profile = self.pending_profile()
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
        profile = self.pending_profile()
        for key, value in (("unexpected", True), ("evidence", [{}]), ("qmi_primary_type", 1)):
            changed = dict(profile, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                packaging.validate_profile(changed)

if __name__ == "__main__":
    unittest.main()
