#!/usr/bin/env python3
"""Tests for tools/generate.py: generated files are up to date, and the
detection regexps agree in every dialect (each checked with the real
engine when vim / node / emacs are installed)."""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import generate as g  # noqa: E402

SPEC = g.load_spec()

SAMPLES = {  # line: is it Basilisk?
    'event init (t = 0) {': True,
    '  event logfile (i++)': True,
    '#include "navier-stokes/centered.h"': True,
    '#  include "two-phase.h"': True,
    '#include "grid/octree.h"': True,
    'scalar f[];': True,
    'face vector uf[];': True,
    'vertex scalar psi[], phi[];': True,
    'symmetric tensor * T[];': True,
    '  foreach()': True,
    '  foreach_face (x)': True,
    'foreach_dimension()': True,
    '#include <stdio.h>': False,
    '#include "mylib.h"': False,
    'int main (void) {': False,
    'scalar s = new scalar;': False,     # not a declaration with []
    'double eventual = 1.;': False,
    '/* foreach loop over things */': False,
    'my_foreach();': False,
    'eventfoo (1);': False,
}


def expected(line):
    return re.search(g.detect_regex(SPEC, g.JS), line) is not None


class Generated(unittest.TestCase):
    def test_up_to_date(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "generate.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_reference_regexp(self):
        for line, want in SAMPLES.items():
            self.assertEqual(expected(line), want, line)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class NodeDialect(unittest.TestCase):
    def test_extension_js_pattern(self):
        with open(os.path.join(ROOT, "vscode", "extension.js")) as f:
            js = f.read()
        decl = re.search(r"^const PATTERN = .*$", js, re.M).group()
        prog = decl + "\nconst lines = " + json.dumps(list(SAMPLES)) + ";\n" \
            "console.log(JSON.stringify(lines.map(l => PATTERN.test(l))));"
        out = subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), list(SAMPLES.values()))


@unittest.skipUnless(shutil.which("vim"), "vim not installed")
class VimDialect(unittest.TestCase):
    def test_ftdetect_pattern(self):
        tmp = tempfile.mkdtemp()
        lines, result = os.path.join(tmp, "lines.txt"), os.path.join(tmp, "out.txt")
        with open(lines, "w") as f:
            f.write("\n".join(SAMPLES) + "\n")
        script = os.path.join(tmp, "t.vim")
        with open(script, "w") as f:
            # through the real entry point (the pattern itself is script-local)
            f.write(f"source {os.path.join(ROOT, 'ftdetect', 'basilisk.vim')}\n"
                    "let out = []\n"
                    f"for l in readfile('{lines}')\n"
                    "  enew!\n  call setline(1, l)\n  setlocal filetype=\n  call BasiliskDetect()\n"
                    "  call add(out, &filetype ==# 'basilisk' ? '1' : '0')\n"
                    "endfor\n"
                    f"call writefile(out, '{result}')\nqa!\n")
        subprocess.run(["vim", "-N", "-u", "NONE", "-i", "NONE", "-es", "-S", script],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        with open(result) as f:
            got = [l == "1" for l in f.read().split()]
        self.assertEqual(got, list(SAMPLES.values()))


@unittest.skipUnless(shutil.which("emacs"), "emacs not installed")
class ElispDialect(unittest.TestCase):
    def test_detect_regexp(self):
        expr = ("(progn (load-file %s) (princ (json-encode (mapcar (lambda (l) "
                "(if (string-match-p basilisk--detect-regexp l) t :json-false)) '(%s)))))"
                % (json.dumps(os.path.join(ROOT, "basilisk-editor.el")),
                   " ".join(json.dumps(l) for l in SAMPLES)))
        out = subprocess.run(["emacs", "-Q", "--batch", "--eval", "(require 'json)", "--eval", expr],
                             capture_output=True, text=True, timeout=60).stdout
        self.assertEqual(json.loads(out.strip().splitlines()[-1]), list(SAMPLES.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
