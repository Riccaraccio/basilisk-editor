#!/usr/bin/env python3
"""Unit tests (no qcc needed): configuration, Basilisk discovery, columns."""
import json, os, re, sys, tempfile, unittest

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
        self.assertEqual(cfg["diagnostics"], "onChange")
        self.assertEqual(cfg["flags"], ["-Wall"])
        self.assertEqual(cfg["root"], self.root)

    def test_precedence_and_paths(self):
        # editor settings < project file; project paths relative to the project file
        p = self.project({"qccFlags": ["-grid=octree", "-Iinc"], "includeDirs": ["../shared"],
                          "diagnostics": "onSave"})
        cfg = b.resolve_config({"basiliskPath": self.root, "qccFlags": ["-O2"],
                                "diagnostics": "off", "debounce": 3}, self.src)
        proj_dir = os.path.dirname(p)
        self.assertEqual(cfg["project"], p)
        self.assertEqual(cfg["diagnostics"], "onSave")
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

    def fake_qcc(self):
        # so that cfg["errors"] is empty where qcc isn't installed (CI)
        q = os.path.join(self.root, "qcc")
        with open(q, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(q, 0o755)
        return {"basiliskPath": self.root, "qcc": q}

    def makefile(self, text, name="Makefile"):
        with open(os.path.join(self.case, name), "w") as f:
            f.write(text)

    def test_makefile_flags(self):
        os.environ["BLSP_TEST_SANDBOX"] = "/opt/sandbox"
        self.addCleanup(os.environ.pop, "BLSP_TEST_SANDBOX", None)
        self.makefile(
            "# a case\n"
            "SRC = $(HOME)/mysrc\n"
            "include $(BASILISK)/Makefile.defs\n"
            "CFLAGS += -O2 -disable-dimensions -I$(SRC) -I ${BLSP_TEST_SANDBOX}/src \\\n"
            "          -Iinc -DNSP=3 -fopenmp -grid=octree  # trailing comment\n"
            "CFLAGS += -I$(BASILISK)/../extra -I$(CURDIR)/cur -I$(NOPE)/x -I$(shell pwd)\n"
            "%.3D.s: CFLAGS += -I/target/specific\n"
            "run:\n"
            "\tCFLAGS += -I/in/a/recipe\n")
        cfg = b.resolve_config(self.fake_qcc(), self.src)
        home = os.path.expanduser("~")
        self.assertEqual(cfg["makefile"], os.path.join(self.case, "Makefile"))
        self.assertEqual(cfg["makefileFlags"], [
            "-disable-dimensions", "-I" + os.path.join(home, "mysrc"), "-I/opt/sandbox/src",
            "-I" + os.path.join(self.case, "inc"), "-DNSP=3", "-grid=octree",
            "-I" + os.path.normpath(os.path.join(self.root, "../extra")),
            "-I" + os.path.join(self.case, "cur")])
        self.assertEqual(cfg["makefileSkipped"], ["-I$(NOPE)/x", "-I$(shell pwd)"])
        self.assertEqual(cfg["errors"], [])          # skipped flags don't block checking
        self.assertEqual(cfg["flags"][-1], "-Wall")  # qccFlags come after the Makefile's
        self.assertIn("/opt/sandbox/src", cfg["idirs"])

    def test_makefile_assignment_resets(self):
        self.makefile("CFLAGS += -Iold\nCFLAGS = -Inew\nCFLAGS ?= -Iignored\n")
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertEqual(cfg["makefileFlags"], ["-I" + os.path.join(self.case, "new")])

    def test_makefile_cflags_self_reference(self):
        self.makefile("CFLAGS += -DA\n"
                      "CFLAGS := $(CFLAGS) -DB\n"
                      "CFLAGS = ${CFLAGS} -DC\n"
                      "ifdef X\nCFLAGS := $(CFLAGS) -DD\nendif\n")
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertEqual(cfg["makefileFlags"], ["-DA", "-DB", "-DC"])
        self.assertEqual(cfg["makefileSkipped"], ["-DD"])

    def test_last_grid_wins_for_completion(self):
        # qcc uses the last -grid=, so completion offers that grid's symbols only
        for g in ("quadtree", "octree", "multigrid"):
            fake = os.path.join(self.root, "grid", g + ".h")
            os.makedirs(os.path.dirname(fake), exist_ok=True)
            open(fake, "w").close()
        self.makefile("CFLAGS += -grid=octree\n")
        self.project({"qccFlags": ["-grid=multigrid"]})
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertEqual([f for f in cfg["flags"] if f.startswith("-grid=")],
                         ["-grid=octree", "-grid=multigrid"])
        files = b.Index().closure(self.src, b.scan("", self.src), cfg)
        grids = sorted(os.path.basename(f) for f in files if os.sep + "grid" + os.sep in f)
        self.assertEqual(grids, ["multigrid.h"])

    def test_makefile_conditionals_skipped(self):
        # ifdef/ifeq aren't evaluated: what they set is neither used nor guessed
        self.makefile(
            "SRC = /a\n"
            "ifdef MPI\n"
            "CFLAGS += -D_MPI=1\n"
            "SRC = /b\n"
            "else ifeq ($(X),y)\n"
            "  ifneq (a,b)\n"
            "  CFLAGS = -Inested\n"
            "  endif\n"
            "else\n"
            "CFLAGS += -DSERIAL\n"
            "endif\n"
            "CFLAGS += -I$(SRC) -DAFTER\n")
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertEqual(cfg["makefileFlags"], ["-DAFTER"])
        self.assertEqual(cfg["makefileSkipped"], [
            "-I$(SRC)", "-D_MPI=1", "-I" + os.path.join(self.case, "nested"), "-DSERIAL"])

    def test_makefile_shell_quotes(self):
        # the shell removes the quotes before qcc sees the flags
        self.makefile("CFLAGS += -DNAME='\"x\"' -DY=\\\"z\\\" -I\"with space\" -DBAD='open\n")
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertEqual(cfg["makefileFlags"], [
            '-DNAME="x"', '-DY="z"', "-I" + os.path.join(self.case, "with space")])
        self.assertEqual(cfg["makefileSkipped"], ["-DBAD='open"])

    def test_makefile_recipes_and_defines_ignored(self):
        self.makefile(
            "run:\n"
            "\techo a \\\n"
            "  CFLAGS += -I/recipe/continuation\n"
            "define BLOCK\n"
            "CFLAGS += -I/in/define\n"
            "endef\n"
            "CFLAGS += -DKEPT\n")
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertEqual(cfg["makefileFlags"], ["-DKEPT"])

    def test_settings_in_every_place(self):
        # a server setting must be declared for VS Code, sent by the
        # extension, and documented (AGENTS.md: "New settings go in DEFAULTS…")
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        with open(os.path.join(root, "vscode", "package.json")) as f:
            props = json.load(f)["contributes"]["configuration"]["properties"]
        with open(os.path.join(root, "vscode", "extension.js")) as f:
            sent = re.search(r"function settings\(\) \{(.*?)\n\}", f.read(), re.S).group(1)
        with open(os.path.join(root, "README.md")) as f:
            readme = f.read()
        client_only = {"autoDetect", "pythonPath"}
        names = {"path" if k == "basiliskPath" else k: k for k in b.DEFAULTS}
        self.assertEqual(set(props), {"basilisk." + n for n in set(names) | client_only})
        for vs, key in names.items():
            self.assertIn("c.get('%s')" % vs, sent, key)
            self.assertIn("| `%s` |" % key, readme, key)

    def test_makefile_off_and_absent(self):
        cfg = b.resolve_config({"basiliskPath": self.root}, self.src)
        self.assertIsNone(cfg["makefile"])
        self.assertEqual(cfg["flags"], ["-Wall"])
        self.makefile("CFLAGS += -Ifoo\n", name="makefile")
        settings = self.fake_qcc()
        cfg = b.resolve_config(settings, self.src)
        self.assertEqual(cfg["makefile"], os.path.join(self.case, "makefile"))  # its real name
        self.project({"useMakefile": False})
        cfg = b.resolve_config(settings, self.src)
        self.assertIsNone(cfg["makefile"])
        self.assertEqual(cfg["flags"], ["-Wall"])
        self.assertEqual(cfg["errors"], [])

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


class Launcher(unittest.TestCase):
    """bin/basilisk-lsp must work through (chains of) symlinks, without
    GNU tools (readlink -f is missing on older macOS)."""

    def test_through_symlinks(self):
        import subprocess
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        tmp = tempfile.mkdtemp()
        a, c = os.path.join(tmp, "a"), os.path.join(tmp, "sub", "c")
        os.makedirs(os.path.dirname(c))
        os.symlink(os.path.abspath(os.path.join(root, "bin", "basilisk-lsp")), a)
        os.symlink("../a", c)                    # relative link to a link
        for exe in (a, c):
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.stdout.strip(), "basilisk-lsp " + b.VERSION, r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
