#!/usr/bin/env python3
"""Basilisk's own sources as a test corpus (needs Basilisk):
- the scanner handles every .c/.h file in $BASILISK without crashing;
- with BASILISK_LSP_SLOW=1: no diagnostics on any of src/examples/*.c,
  which all compile (about 2 s per file)."""
import glob, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "server"))
import basilisk_lsp as b  # noqa: E402

CFG = b.Server().config(os.path.join(tempfile.gettempdir(), "x.c"))
BASILISK = CFG["root"]


@unittest.skipUnless(BASILISK, "Basilisk not available")
class Corpus(unittest.TestCase):
    def test_scanner_on_all_sources(self):
        files = glob.glob(os.path.join(BASILISK, "**", "*.[ch]"), recursive=True)
        self.assertGreater(len(files), 100)
        nsym = 0
        for f in files:
            with open(f, encoding="utf-8", errors="replace") as fp:
                nsym += len(b.scan(fp.read(), f).symbols)
        self.assertGreater(nsym, 1000)

    def test_solver_headers_resolve(self):
        fi = b.scan('#include "navier-stokes/centered.h"\n', "/tmp/x.c")
        files = b.Index().closure("/tmp/x.c", fi, CFG)
        names = {os.path.relpath(f, BASILISK) for f in files}
        self.assertTrue({"navier-stokes/centered.h", "utils.h", "common.h"} <= names, names)

    @unittest.skipUnless(os.environ.get("BASILISK_LSP_SLOW") and CFG["qccExe"],
                         "set BASILISK_LSP_SLOW=1 (needs qcc; ~2 s per example)")
    def test_no_false_positives_on_examples(self):
        examples = sorted(glob.glob(os.path.join(BASILISK, "examples", "*.c")))
        self.assertGreater(len(examples), 10)
        noisy = {}
        for f in examples:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "server", "basilisk_lsp.py"), "--lint", f],
                               capture_output=True, text=True, timeout=300)
            if r.stdout.strip():
                noisy[os.path.basename(f)] = r.stdout.strip().splitlines()[0]
        self.assertEqual(noisy, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
