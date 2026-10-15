#!/usr/bin/env python3
"""Exercise the ACTUAL stopped-container collector, using harmless canaries."""
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "tests/fixtures/diagnostic-collector-review-1.sh"
NEW = ROOT / "build/collect-evidence.py"
SHA = "a" * 40
CANARY = b"HARMLESS OUTSIDE FIXTURE CANARY; NOT A HOST SECRET"
OLD_SHA = "07873bc4548c7615189c7afe652bc96df0c69f24f75f0ba6235ecc0291442604"


class CollectorTests(unittest.TestCase):
    def layout(self, parent):
        workspace = parent / "workspace"
        evidence = workspace / ".artifacts/mm-packages" / SHA
        (evidence / "first").mkdir(parents=True)
        (evidence / "second").mkdir()
        return workspace, evidence

    def link(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError:
            if os.name != "nt":
                raise
            self.skipTest("Windows cannot create symlinks; genuine native RED/GREEN pending")

    def invoke(self, evidence, destination, success=False):
        return subprocess.run([sys.executable, str(NEW), str(evidence), str(destination),
                               "success" if success else "failure"], capture_output=True, text=True)

    def assert_clean(self, destination):
        for path in destination.rglob("*"):
            self.assertFalse(path.is_symlink())
            if path.is_file():
                self.assertNotIn(CANARY, path.read_bytes())
        self.assertFalse((destination / "candidate").exists())

    def old_collect(self, workspace):
        self.assertEqual(hashlib.sha256(OLD.read_bytes()).hexdigest(), OLD_SHA)
        environment = dict(os.environ, GITHUB_WORKSPACE=str(workspace), PROVIDER_PACKAGE_SHA=SHA)
        result = subprocess.run(["bash", str(OLD)], env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_regular_and_early_failure_diagnostics(self):
        for early in (False, True):
            with self.subTest(early=early), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                _, evidence = self.layout(parent)
                (evidence / "first/bootstrap.log").write_text("regular harmless log")
                if not early:
                    reports = evidence / "first/output/reports"
                    reports.mkdir(parents=True)
                    (reports / "test.log").write_text("actual regular report fixture")
                    (evidence / "first/output/manifest.json").write_text("{}")
                destination = parent / "protected-upload"
                result = self.invoke(evidence, destination)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((destination / "diagnostics/first/bootstrap.log").read_text(), "regular harmless log")
                self.assert_clean(destination)

    def test_leaf_symlinks_reproduce_old_leak_and_new_rejection(self):
        inputs = ("first/execution.log", "first/bootstrap.log", "first/output/manifest.json",
                  "second/execution.log", "second/bootstrap.log", "second/output/manifest.json",
                  "second/comparison.log", "second/output.comparison.json")
        for relative in inputs:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                workspace, evidence = self.layout(parent)
                canary = parent / "outside-canary.txt"
                canary.write_bytes(CANARY)
                link = evidence / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                self.link(link, canary)
                self.old_collect(workspace)
                self.assertTrue(any(CANARY in path.read_bytes() for path in (evidence / "diagnostics").rglob("*") if path.is_file()),
                                "retained actual old collector did not reproduce the leak")
                print("RED reproduced: actual review-1 collector followed " + relative)
                # Old diagnostics contain synthetic canary bytes; remove only the
                # test-owned old output before testing the corrected collector.
                shutil.rmtree(evidence / "diagnostics")
                destination = parent / "protected-upload"
                result = self.invoke(evidence, destination)
                self.assertNotEqual(result.returncode, 0)
                self.assert_clean(destination)

    def test_parent_and_root_symlinks_rejected(self):
        for relative in ("first", "first/output", "first/output/reports", "diagnostics", "."):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp)
                workspace, evidence = self.layout(parent)
                outside = parent / "outside"
                outside.mkdir()
                (outside / "bootstrap.log").write_bytes(CANARY)
                (outside / "manifest.json").write_bytes(CANARY)
                (outside / "test.log").write_bytes(CANARY)
                if relative == ".":
                    (outside / "first").mkdir()
                    (outside / "first/bootstrap.log").write_bytes(CANARY)
                link = evidence if relative == "." else evidence / relative
                if link.exists():
                    shutil.rmtree(link)
                link.parent.mkdir(parents=True, exist_ok=True)
                self.link(link, outside, directory=True)
                if relative in ("first", "first/output", "."):
                    self.old_collect(workspace)
                    self.assertTrue(any(CANARY in path.read_bytes() for path in (evidence / "diagnostics").rglob("*") if path.is_file()))
                    print("RED reproduced: actual review-1 collector followed parent " + relative)
                    shutil.rmtree(evidence / "diagnostics")
                destination = parent / "protected-upload"
                result = self.invoke(evidence, destination)
                self.assertNotEqual(result.returncode, 0)
                self.assert_clean(destination)

    def test_symlinked_destination_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            _, evidence = self.layout(parent)
            outside = parent / "outside"
            outside.mkdir()
            (outside / "canary").write_bytes(CANARY)
            link = parent / "upload-parent"
            self.link(link, outside, directory=True)
            result = self.invoke(evidence, link / "upload")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(outside.iterdir()), [outside / "canary"])

    def test_existing_destination_is_never_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            _, evidence = self.layout(parent)
            destination = parent / "protected-upload"
            destination.mkdir()
            (destination / "existing").write_bytes(CANARY)
            result = self.invoke(evidence, destination)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination / "existing").read_bytes(), CANARY)
            self.assertFalse((destination / "diagnostics").exists())

    def test_mismatched_source_never_materializes_candidate(self):
        spec = importlib.util.spec_from_file_location("packaging_tests", ROOT / "tests/test-packaging.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            _, evidence = self.layout(parent)
            fixture = module.PackagingTests()
            for build in ("first", "second"):
                fixture.bundle(evidence / build / "output")
            positive = parent / "matching-upload"
            result = self.invoke(evidence, positive, success=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((positive / "candidate/packages/modemmanager.deb").is_file())
            self.assertTrue(json.loads((positive / "diagnostics/collection.json").read_text())["candidate_materialized"])
            path = evidence / "second/output"
            (path / "source/patches/series").write_text("CHANGED SYNTHETIC SOURCE")
            module.packaging.manifest(path, "a" * 40, "123", "b" * 64)
            destination = parent / "protected-upload"
            result = self.invoke(evidence, destination, success=True)
            self.assertNotEqual(result.returncode, 0)
            self.assert_clean(destination)
            self.assertFalse(json.loads((destination / "diagnostics/host-comparison.json").read_text())["payloads_match"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
