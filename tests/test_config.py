#!/usr/bin/env python3
"""Unit tests (no qcc needed): configuration, Basilisk discovery, columns."""
import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import basilisk_lsp as b  # noqa: E402


def fake_basilisk(d):
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "common.h"), "w").close()
    return d


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = fake_basilisk(os.path.join(self.tmp, "basilisk", "src"))
        self.case = os.path.join(self.tmp, "proj", "case")
        os.makedirs(self.case)
        self.src = os.path.join(self.case, "drop.c")
        open(self.src, "w").close()

    def project(self, data, where=None):
        p = os.path.join(where or os.path.dirname(self.case), b.PROJECT_FILE)
        with open(p, "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        return p

    def test_defaults(self):
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertEqual(cfg["diagnostics"], "onSave")
        self.assertEqual(cfg["flags"], ["-Wall"])
        self.assertEqual(cfg["root"], self.root)

    def test_precedence_and_paths(self):
        # editor settings < project file; project paths relative to the project file
        p = self.project({"qccFlags": ["-grid=octree", "-Iinc"], "includeDirs": ["../shared"],
                          "diagnostics": "onChange"})
        cfg = b.resolve_config({"basiliskPath": self.root, "qccFlags": ["-O2"],
                                "diagnostics": "off", "debounce": 3}, self.src)
        proj_dir = os.path.dirname(p)
        self.assertEqual(cfg["project"], p)
        self.assertEqual(cfg["diagnostics"], "onChange")
        self.assertEqual(cfg["debounce"], 3)            # editor setting kept
        self.assertIn("-grid=octree", cfg["flags"])
        self.assertNotIn("-O2", cfg["flags"])            # replaced, not merged
        self.assertIn(os.path.join(proj_dir, "inc"), cfg["idirs"])
        self.assertIn(os.path.normpath(os.path.join(proj_dir, "../shared")), cfg["idirs"])

    def test_nearest_project_file_wins(self):
        self.project({"qccFlags": ["-grid=octree"]})
        self.project({"qccFlags": ["-grid=bitree"]}, where=self.case)
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertIn("-grid=bitree", cfg["flags"])

    def test_bad_project_file(self):
        self.project("{ not json")
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertTrue(any(b.PROJECT_FILE in e for e in cfg["errors"]))
        self.project({"bogus": 1})
        os.utime(os.path.join(os.path.dirname(self.case), b.PROJECT_FILE), (1, 1))
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertTrue(any("unknown setting(s) bogus" in e for e in cfg["errors"]))

    def test_basilisk_from_project_file(self):
        self.project({"basiliskPath": "../basilisk/src"})
        cfg = b.resolve_config({}, self.src)
        self.assertEqual(cfg["root"], self.root)

    def test_basilisk_not_found_message(self):
        old = dict(os.environ)
        try:
            os.environ.pop("BASILISK", None)
            os.environ["PATH"] = "/nonexistent"
            saved, b.COMMON_ROOTS = b.COMMON_ROOTS, []
            cfg = b.resolve_config({}, self.src)
        finally:
            b.COMMON_ROOTS = saved
            os.environ.clear()
            os.environ.update(old)
        self.assertIsNone(cfg["root"])
        self.assertTrue(any("cannot find Basilisk" in e and "$BASILISK" in e for e in cfg["errors"]))

    def test_editor_settings_vscode_shape(self):
        s = b.Server()
        s.set_config({"basilisk": {"path": self.root, "qccFlags": ["-Wall"]}})
        self.assertEqual(s.settings["basiliskPath"], self.root)


class Columns(unittest.TestCase):
    def test_utf16(self):
        self.assertEqual(b.idx_to_u16("ρx", 1), 1)        # BMP: 1 unit
        self.assertEqual(b.idx_to_u16("😀x", 1), 2)       # astral: 2 units
        self.assertEqual(b.u16_to_idx("😀x", 2), 1)

    def test_gcc_byte_columns(self):
        s = "/* ρ */ x = 1;"
        self.assertEqual(b.byte_to_idx(s, s.encode().index(b"x")), s.index("x"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
