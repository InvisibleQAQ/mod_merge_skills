import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "merge_assets", ROOT / "elden-ring-mod-merge/scripts/merge_assets.py")
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)


class AssetsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="er-merge-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b = self.root / "a", self.root / "b"
        for folder in (self.a, self.b):
            folder.mkdir()
            (folder / "regulation.bin").write_bytes(b"input regulation fixture")
        self.report = self.root / "plan.json"
        self.reg = self.root / "verified.bin"
        self.reg.write_bytes(b"codec output fixture")
        self.verification = self.root / "verified.bin.verified.json"
        assets.write_new(self.verification, {
            "schema": "er-regulation-build-v1", "status": "verified",
            "inputs": {"a": assets.digest(self.a / "regulation.bin"),
                       "b": assets.digest(self.b / "regulation.bin"), "base": "fixture"},
            "output": str(self.reg), "outputSha256": assets.digest(self.reg),
        })

    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return assets.main([str(arg) for arg in args])

    def scan(self, *extra):
        return self.invoke("scan", "--a", self.a, "--b", self.b,
                           "--report", self.report, *extra)

    def assemble(self, *extra):
        return self.invoke("assemble", "--report", self.report, "--regulation", self.reg,
                           "--verification", self.verification,
                           "--output", self.root / "result", "--receipt", self.root / "receipt.json", *extra)

    def test_disjoint_and_identical_files_and_exclusions(self):
        (self.a / "one.txt").write_bytes(b"A")
        (self.b / "two.txt").write_bytes(b"B")
        for folder in (self.a, self.b):
            (folder / "same.txt").write_bytes(b"same")
            (folder / "c0000.anibnd.dcx").write_bytes(folder.name.encode())
            (folder / "c0000.hks").write_bytes(b"excluded")
            (folder / "eventnameid.txt").write_bytes(b"excluded")
        self.assertEqual(self.scan(), 0)
        self.assertEqual(self.assemble(), 0)
        output = self.root / "result"
        self.assertEqual({p.name for p in output.iterdir()},
                         {"one.txt", "two.txt", "same.txt", "regulation.bin"})
        self.assertEqual((output / "regulation.bin").read_bytes(), self.reg.read_bytes())
        receipt = assets.read_json(self.root / "receipt.json")
        self.assertEqual(len(receipt["excluded"]), 3)
        self.assertFalse(receipt["gameplay_verified"])

    def test_conflict_requires_bound_explicit_decision(self):
        (self.a / "x.bin").write_bytes(b"A")
        (self.b / "x.bin").write_bytes(b"B")
        self.assertEqual(self.scan(), 2)
        self.assertEqual(self.assemble(), 1)
        self.assertFalse((self.root / "result").exists())
        decisions = self.root / "decisions.json"
        assets.write_new(decisions, {"report_sha256": assets.digest(self.report),
                                    "decisions": {"x.bin": "b"}})
        self.assertEqual(self.assemble("--decisions", decisions), 0)
        self.assertEqual((self.root / "result/x.bin").read_bytes(), b"B")

    def test_baseline_and_overlay_absence(self):
        base = self.root / "base"
        base.mkdir()
        (base / "x.bin").write_bytes(b"C")
        (self.a / "x.bin").write_bytes(b"C")
        (self.b / "x.bin").write_bytes(b"B")
        (self.a / "only.txt").write_bytes(b"keep; absent in B is not deletion")
        self.assertEqual(self.scan("--base-files", base), 0)
        self.assertEqual(self.assemble(), 0)
        self.assertEqual((self.root / "result/x.bin").read_bytes(), b"B")
        self.assertTrue((self.root / "result/only.txt").is_file())

    def test_changed_input_is_not_assembled(self):
        self.assertEqual(self.scan(), 0)
        (self.a / "new.txt").write_bytes(b"changed")
        self.assertEqual(self.assemble(), 1)
        self.assertFalse((self.root / "result").exists())

    def test_no_overwrite_and_no_path_traversal(self):
        self.assertEqual(self.scan(), 0)
        self.assertEqual(self.scan(), 1)
        for path in ("../input", "/absolute", "C:/file", "x\\y", "a//b"):
            with self.assertRaises(ValueError):
                assets.safe_relative(path)

    def test_wrong_mod_root_is_rejected(self):
        (self.a / "nested").mkdir()
        (self.a / "nested/regulation.bin").write_bytes(b"nested")
        self.assertEqual(self.scan(), 1)

    def test_base_changed_after_scan_is_rejected(self):
        base = self.root / "base"
        base.mkdir()
        for folder, value in ((base, b"C"), (self.a, b"A"), (self.b, b"B")):
            (folder / "x.bin").write_bytes(value)
        self.assertEqual(self.scan("--base-files", base), 2)
        decisions = self.root / "decisions.json"
        assets.write_new(decisions, {"report_sha256": assets.digest(self.report),
                                    "decisions": {"x.bin": "base"}})
        (base / "x.bin").write_bytes(b"changed")
        self.assertEqual(self.assemble("--decisions", decisions), 1)

    def test_base_cannot_be_a_mod_root(self):
        self.assertEqual(self.scan("--base-files", self.a), 1)

    def test_base_changed_even_when_b_selected(self):
        base = self.root / "base"
        base.mkdir()
        for folder, value in ((base, b"C"), (self.a, b"A"), (self.b, b"B")):
            (folder / "x.bin").write_bytes(value)
        self.assertEqual(self.scan("--base-files", base), 2)
        decisions = self.root / "decisions.json"
        assets.write_new(decisions, {"report_sha256": assets.digest(self.report),
                                    "decisions": {"x.bin": "b"}})
        (base / "x.bin").write_bytes(b"changed")
        self.assertEqual(self.assemble("--decisions", decisions), 1)

    def test_verified_regulation_cannot_be_replaced(self):
        self.assertEqual(self.scan(), 0)
        self.reg.write_bytes(b"not the verified regulation")
        self.assertEqual(self.assemble(), 1)
        self.assertFalse((self.root / "result").exists())

    def test_verification_must_match_scanned_mods(self):
        self.assertEqual(self.scan(), 0)
        verification = assets.read_json(self.verification)
        verification["inputs"]["a"] = "ANOTHER-TASK"
        self.verification.write_text(json.dumps(verification), encoding="utf-8")
        self.assertEqual(self.assemble(), 1)


if __name__ == "__main__":
    unittest.main()
