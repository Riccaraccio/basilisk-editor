#!/usr/bin/env python3
"""Diagnostics without qcc: replays the qcc runs recorded in
tests/fixtures/diagnostics/*/qcc.json (see record_fixtures.py) through
the whole checking path (header modes, output parsing, mapping onto the
document) and compares with expected.json."""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import basilisk_lsp as b  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "diagnostics")
SCENARIOS = sorted(d for d in os.listdir(FIXTURES) if os.path.isfile(os.path.join(FIXTURES, d, "qcc.json")))


class Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # a fake Basilisk: enough for the configuration to resolve
        cls.root = tempfile.mkdtemp(prefix="fake-basilisk-")
        open(os.path.join(cls.root, "common.h"), "w").close()
        qcc = os.path.join(cls.root, "qcc")
        open(qcc, "w").close()
        os.chmod(qcc, 0o755)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)
        b.QCC_REPLAY = None

    def replay(self, name):
        case = os.path.join(FIXTURES, name)
        with open(os.path.join(case, "scenario.json")) as f:
            scenario = json.load(f)
        with open(os.path.join(case, "qcc.json")) as f:
            runs = json.load(f)
        with open(os.path.join(case, "expected.json")) as f:
            expected = json.load(f)

        def fake_qcc(files, main, tmp):
            for r in runs:
                if r["main"] == main and r["files"] == sorted(files):
                    out = (r["out"].replace("$TMP", tmp).replace("$CASE", case)
                           .replace("$BASILISK", self.root))
                    return out, r["returncode"]
            self.fail(f"{name}: unexpected qcc run {main} {sorted(files)}")

        b.QCC_REPLAY = fake_qcc
        server = b.Server()
        server.set_config({"basiliskPath": self.root})
        path = os.path.join(case, scenario["file"])
        with open(path, encoding="utf-8") as f:
            text = f.read()
        diags, err = b.check(server, path, text)
        self.assertIsNone(err)
        self.assertEqual(diags, expected)

    def test_scenarios_present(self):
        self.assertGreaterEqual(len(SCENARIOS), 8)


def make_test(name):
    return lambda self: self.replay(name)


for _name in SCENARIOS:
    setattr(Replay, "test_" + _name, make_test(_name))


class Parsing(unittest.TestCase):
    """Corner cases of qcc/gcc output, without fixtures."""

    def parse(self, out, rc=1):
        return b.parse_qcc_output(out, rc, lambda f: "/r/" + f, "/r/t.c")

    def test_error_without_location(self):
        raw = self.parse("qcc: error: cannot parse input (missing closing braces?)\n")
        self.assertEqual(raw, [["/r/t.c", 1, None, "error", "cannot parse input (missing closing braces?)", None]])

    def test_failure_with_unknown_output_is_never_clean(self):
        raw = self.parse("something unexpected\n", rc=2)
        self.assertEqual(len(raw), 1)
        self.assertIn("qcc failed (exit status 2)", raw[0][4])

    def test_success_with_unknown_output(self):
        self.assertEqual(self.parse("some chatter\n", rc=0), [])

    def test_function_context_and_continuation(self):
        out = ("x.c: In function ‘init_0’:\n"
               "x.c:5: warning: Basilisk C parse error near `a\n  b'\n"
               "x.c: At top level:\n")
        raw = self.parse(out, rc=0)
        self.assertEqual(raw[0][:4], ["/r/x.c", 5, None, "warning"])
        self.assertEqual(raw[0][4], "Basilisk C parse error near `a\n  b'")
        self.assertEqual(raw[0][5], "init_0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
