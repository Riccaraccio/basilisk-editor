#!/usr/bin/env python3
"""
Records the qcc runs behind tests/fixtures/diagnostics/*/ (needs Basilisk).

    python3 tests/record_fixtures.py [scenario ...]

For each scenario directory (scenario.json: {"file": ...}), checks the
file like the language server does and writes:
  qcc.json       the qcc invocations and their output, with machine paths
                 replaced by $TMP, $CASE and $BASILISK
  expected.json  the resulting diagnostics
tests/test_diagnostics.py replays qcc.json without qcc and compares.
Re-record after changing the fixtures or when qcc's output changes.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
import basilisk_lsp as b  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "diagnostics")


def sanitize(text, subs):
    for real, placeholder in sorted(subs.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(real, placeholder)
    return text


def record(name):
    case = os.path.join(FIXTURES, name)
    with open(os.path.join(case, "scenario.json")) as f:
        scenario = json.load(f)
    path = os.path.join(case, scenario["file"])
    server = b.Server()
    root = server.config(path)["root"]
    if not root:
        sys.exit("Basilisk not found: set $BASILISK")
    runs = []

    def rec(files, main, out, returncode, tmp):
        subs = {tmp: "$TMP", os.path.realpath(tmp): "$TMP", case: "$CASE",
                os.path.realpath(case): "$CASE", root: "$BASILISK", os.path.realpath(root): "$BASILISK"}
        runs.append({"main": main, "files": sorted(files), "returncode": returncode,
                     "out": sanitize(out, subs)})

    b.QCC_RECORD = rec
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        diags, err = b.check(server, path, text)
    finally:
        b.QCC_RECORD = None
    if diags is None:
        sys.exit(f"{name}: {err}")
    with open(os.path.join(case, "qcc.json"), "w") as f:
        json.dump(runs, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(case, "expected.json"), "w") as f:
        json.dump(diags, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"{name}: {len(runs)} qcc run(s), {len(diags)} diagnostic(s)")


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(d for d in os.listdir(FIXTURES)
                                   if os.path.isfile(os.path.join(FIXTURES, d, "scenario.json")))
    for n in names:
        record(n)
