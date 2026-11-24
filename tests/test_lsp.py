#!/usr/bin/env python3
"""End-to-end test: drives basilisk_lsp.py over stdio like an editor would.
Needs Basilisk (qcc); skipped otherwise. Run alone: python3 tests/test_lsp.py"""
import json, os, subprocess, sys, tempfile, threading, queue, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "server", "basilisk_lsp.py")

SRC = '''#include "navier-stokes/centered.h"
#include "vof.h"

scalar f[], * interfaces = {f};
double rho1 = 1.;

int main() {
  init_grid (64);
  run();
}

/** Initial condition */
event init (t = 0) {
  foreach()
    f[] = x < 0.5 ? undefined_var : 0.;
  output_field ({f}, stdout);
}
'''

class Client:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE)
        self.q, self.id = queue.Queue(), 0
        threading.Thread(target=self.reader, daemon=True).start()
    def reader(self):
        while True:
            h = {}
            while True:
                l = self.p.stdout.readline()
                if not l: return
                l = l.decode().strip()
                if not l: break
                k, _, v = l.partition(":"); h[k.lower()] = v.strip()
            self.q.put(json.loads(self.p.stdout.read(int(h["content-length"]))))
    def send(self, m):
        m["jsonrpc"] = "2.0"; b = json.dumps(m).encode()
        self.p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); self.p.stdin.flush()
    def request(self, method, params):
        self.id += 1; self.send({"id": self.id, "method": method, "params": params})
        while True:
            m = self.q.get(timeout=30)
            if m.get("id") == self.id: return m.get("result")
            self.pending.append(m)
    def notify(self, method, params): self.send({"method": method, "params": params})
    pending = []
    def wait(self, method, timeout=60):
        for m in self.pending:
            if m.get("method") == method: self.pending.remove(m); return m["params"]
        end = time.time() + timeout
        while time.time() < end:
            m = self.q.get(timeout=timeout)
            if m.get("method") == method: return m["params"]

fails = 0
def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(info)[:300]))
    fails += not cond

def pos(line, text):
    l = SRC.split("\n")[line]; return {"line": line, "character": l.index(text) + 1}


def diags_for(client, version, timeout):
    """publishDiagnostics for `version`, or None within `timeout` seconds."""
    def match(m):
        return m.get("method") == "textDocument/publishDiagnostics" and m["params"].get("version") == version
    for m in client.pending:
        if match(m):
            return m["params"]["diagnostics"]
    end = time.time() + timeout
    while time.time() < end:
        try:
            m = client.q.get(timeout=max(0.1, end - time.time()))
        except queue.Empty:
            return None
        if match(m):
            return m["params"]["diagnostics"]
    return None


def protocol():
    """Runs the whole scenario; returns the number of failed checks."""
    global fails
    fails = 0
    d = tempfile.mkdtemp()
    path = os.path.join(d, "test.c"); open(path, "w").write(SRC)
    uri = "file://" + path
    c = Client()
    r = c.request("initialize", {"processId": None, "rootUri": None, "capabilities": {
        "textDocument": {"completion": {"completionItem": {"snippetSupport": True}}}}})
    check("initialize", r["capabilities"]["hoverProvider"])
    c.notify("initialized", {})
    c.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "basilisk", "version": 1, "text": SRC}})

    h = c.request("textDocument/hover", {"textDocument": {"uri": uri}, "position": pos(15, "output_field")})
    check("hover output_field", h and "output_field" in h["contents"]["value"] and "output.h" in h["contents"]["value"], h)
    h = c.request("textDocument/hover", {"textDocument": {"uri": uri}, "position": pos(13, "foreach")})
    check("hover foreach", h and "leaf cells" in h["contents"]["value"], h)
    h = c.request("textDocument/hover", {"textDocument": {"uri": uri}, "position": pos(0, "centered")})
    check("hover include", h and "Navier" in h["contents"]["value"], h)

    r = c.request("textDocument/definition", {"textDocument": {"uri": uri}, "position": pos(15, "output_field")})
    check("definition output_field", r and r[0]["uri"].endswith("/output.h"), r)
    r = c.request("textDocument/definition", {"textDocument": {"uri": uri}, "position": pos(12, "init")})
    check("definition event init (user + solver)", r and len(r) >= 2 and any("centered.h" in x["uri"] for x in r), r)
    r = c.request("textDocument/definition", {"textDocument": {"uri": uri}, "position": pos(1, "vof")})
    check("definition include", r and r[0]["uri"].endswith("src/vof.h"), r)

    r = c.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
    names = [s["name"] for s in r]
    check("documentSymbol", {"f", "interfaces", "rho1", "main", "event init"} <= set(names), names)

    r = c.request("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": 14, "character": 4}})
    labels = {i["label"] for i in r["items"]}
    check("completion symbols", {"foreach", "foreach_face", "output_field", "u", "uf", "statsf", "rho1", "Delta"} <= labels,
          sorted(labels)[:50])
    it = [i for i in r["items"] if i["label"] == "statsf"][0]
    it = c.request("completionItem/resolve", it)
    check("completion resolve docs", "documentation" in it, it)

    src2 = SRC.replace("  output_field", "  u.")
    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": src2}]})
    r = c.request("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": 15, "character": 4}})
    check("completion u.", {i["label"] for i in r["items"]} == {"x", "y", "z"}, r)

    src3 = src2.replace("  u.", '#include "navier-stokes/')
    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 3}, "contentChanges": [{"text": src3}]})
    line = src3.split("\n")[15]
    r = c.request("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": 15, "character": len(line)}})
    check("completion #include", any(i["label"] == "navier-stokes/centered.h" for i in r["items"]), r and r["items"][:3])

    # diagnostics: back to the original text with undefined_var inside foreach
    c.pending.clear()
    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 4}, "contentChanges": [{"text": SRC}]})
    c.notify("textDocument/didSave", {"textDocument": {"uri": uri}})
    dg = None
    end = time.time() + 60
    while time.time() < end:
        dg = c.wait("textDocument/publishDiagnostics")
        if dg and dg.get("version") == 4: break
    msgs = [(x["range"]["start"]["line"], x["message"]) for x in dg["diagnostics"]]
    check("diagnostic undefined_var anchored on line 15",
          any(l == 14 and "undefined_var" in m for l, m in msgs), msgs)

    # B1: completion documentation must come from the document the item was made for
    c.pending.clear()
    r = c.request("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": 14, "character": 4}})
    statsf = [i for i in r["items"] if i["label"] == "statsf"][0]
    path2 = os.path.join(d, "other.c"); open(path2, "w").write("int main() {}\n")
    uri2 = "file://" + path2
    c.notify("textDocument/didOpen", {"textDocument": {"uri": uri2, "languageId": "basilisk", "version": 1,
                                                       "text": "int main() {}\n"}})
    c.request("textDocument/hover", {"textDocument": {"uri": uri2}, "position": {"line": 0, "character": 5}})
    it = c.request("completionItem/resolve", statsf)
    check("resolve uses the item's own document (B1)",
          "utils.h" in it.get("documentation", {}).get("value", ""), it)

    # default diagnostics mode is onChange: typing alone runs qcc (no save)
    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 5},
                                        "contentChanges": [{"text": SRC + "oops\n"}]})
    dg = diags_for(c, 5, 60)
    check("onChange default: checked while typing", bool(dg) and any(x["severity"] == 1 for x in dg), dg)
    c.request("shutdown", None); c.notify("exit", None)

    # a client asking for onSave: typing alone does not run qcc, saving does
    c2 = Client()
    c2.pending = []
    c2.request("initialize", {"processId": None, "rootUri": None, "capabilities": {},
                              "initializationOptions": {"diagnostics": "onSave", "debounce": 0.2}})
    c2.notify("initialized", {})
    c2.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "basilisk", "version": 1, "text": SRC}})
    c2.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2},
                                         "contentChanges": [{"text": SRC + "oops\n"}]})
    check("onSave setting: no check while typing", diags_for(c2, 2, 4) is None)
    c2.notify("textDocument/didSave", {"textDocument": {"uri": uri}})
    dg = diags_for(c2, 2, 60)
    check("onSave setting: checked on save", bool(dg) and any(x["severity"] == 1 for x in dg), dg)
    c2.request("shutdown", None); c2.notify("exit", None)
    return fails


def basilisk_available():
    sys.path.insert(0, os.path.join(HERE, "..", "server"))
    import basilisk_lsp
    cfg = basilisk_lsp.Server().config(os.path.join(tempfile.gettempdir(), "x.c"))
    return bool(cfg["root"] and cfg["qccExe"])


@unittest.skipUnless(basilisk_available(), "Basilisk (qcc) not available")
class EndToEnd(unittest.TestCase):
    def test_protocol(self):
        self.assertEqual(protocol(), 0, "failed checks (see PASS/FAIL lines above)")


if __name__ == "__main__":
    n = protocol()
    print("FAILURES:", n)
    sys.exit(1 if n else 0)
