#!/usr/bin/env python3
"""Unit tests (no qcc needed) for the symbol scanner and comment handling."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import basilisk_lsp as b  # noqa: E402

HEADER = r'''/**
# My solver

Some introduction. */

#include "utils.h"
#define SQ(x) ((x)*(x))
#define NCOMP 3

/** The volume fraction. */
scalar f[], * interfaces = {f};
face vector uf[];
(const) scalar rho = unity;
double rho1 = 1., rho2 = 1.; // densities

typedef struct {
  double a, b;
} Pair;

/**
Returns the sum of *s*. */
trace
double total (scalar s,
              double w = 1.)
{
  return 0.;
}

static double
helper (int n)
{
  return n;
}

double declared_only (int n);

macro foreach_thing (int n) {
  {...}
}

/** Default initial condition. */
event init (t = 0) {
  if (true)
    helper (1);
}
'''


class Scanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fi = b.scan(HEADER, "/x/my.h")
        cls.sym = {}
        for s in cls.fi.symbols:
            cls.sym.setdefault(s.name, s)

    def test_title_and_includes(self):
        self.assertEqual(self.fi.title, "My solver")
        self.assertEqual([(d, n) for d, n, _ in self.fi.includes], [('"', "utils.h")])

    def test_kinds(self):
        kinds = {n: s.kind for n, s in self.sym.items()}
        self.assertEqual(kinds["SQ"], "define")
        self.assertEqual(kinds["NCOMP"], "define")
        for n in ("f", "interfaces", "uf", "rho"):
            self.assertEqual(kinds[n], "field", n)
        self.assertEqual(kinds["rho1"], "variable")
        self.assertEqual(kinds["Pair"], "type")
        for n in ("total", "helper", "declared_only"):
            self.assertEqual(kinds[n], "function", n)
        self.assertEqual(kinds["foreach_thing"], "macro")
        self.assertEqual(kinds["init"], "event")
        self.assertNotIn("if", kinds)

    def test_signatures(self):
        self.assertEqual(self.sym["total"].sig, "double total (scalar s, double w = 1.)")
        self.assertEqual(self.sym["helper"].sig, "static double helper (int n)")
        self.assertEqual(self.sym["uf"].sig, "face vector uf[]")
        self.assertEqual(self.sym["interfaces"].sig, "scalar * interfaces = {f}")
        self.assertEqual(self.sym["rho"].ftype, "(const) scalar")
        self.assertEqual(self.sym["init"].sig, "event init (t = 0)")

    def test_documentation(self):
        self.assertEqual(self.sym["f"].doc, "The volume fraction.")
        self.assertEqual(self.sym["total"].doc, "Returns the sum of *s*.")   # across `trace`
        self.assertEqual(self.sym["init"].doc, "Default initial condition.")
        self.assertEqual(self.sym["rho1"].doc, "densities")                  # trailing comment
        self.assertEqual(self.sym["helper"].doc, "")

    def test_positions(self):
        s = self.sym["total"]
        self.assertEqual(HEADER.split("\n")[s.line][s.col:s.col + 5], "total")


class Comments(unittest.TestCase):
    def test_blanking_keeps_positions(self):
        text = 'a /* x\ny */ b "s/*t" // c\nd'
        code, blocks, trailing = b.blank_comments(text)
        self.assertEqual(len(code), len(text))
        self.assertEqual(code.count("\n"), text.count("\n"))
        self.assertNotIn("x", code)
        self.assertIn('"    "', code)                  # string contents blanked
        self.assertIn(1, trailing)                     # `// c` follows code
        self.assertTrue(code.endswith("d"))

    def test_clean_comment(self):
        self.assertEqual(b.clean_comment("/**\n * one\n * two\n */"), "one\ntwo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
