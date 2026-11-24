#!/usr/bin/env python3
"""Configuration files for editors we can't run in tests (editors/,
ale_linters/): they parse, have the documented structure, and start
basilisk-lsp. The ALE linter is loaded in vim against a stub of ALE's API."""
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
ED = os.path.join(ROOT, "editors")


def load_json(*parts):
    with open(os.path.join(ED, *parts)) as f:
        return json.load(f)


def is_server(cmd):
    return os.path.basename(cmd) == "basilisk-lsp"


class Snippets(unittest.TestCase):
    @unittest.skipUnless(sys.version_info >= (3, 11), "tomllib needs Python 3.11")
    def test_helix(self):
        import tomllib
        with open(os.path.join(ED, "helix", "languages.toml"), "rb") as f:
            d = tomllib.load(f)
        self.assertTrue(is_server(d["language-server"]["basilisk-lsp"]["command"]))
        c = [lang for lang in d["language"] if lang["name"] == "c"]
        self.assertEqual(c[0]["language-servers"], ["basilisk-lsp"])

    def test_kate(self):
        c = load_json("kate", "lspclient-settings.json")["servers"]["c"]
        self.assertTrue(is_server(c["servers"]["basilisk-lsp"]["command"][0]))
        self.assertTrue(c["servers"]["clangd"]["disabled"])

    def test_sublime(self):
        s = load_json("sublime", "LanguageServers.sublime-settings")["basilisk-lsp"]
        self.assertTrue(s["enabled"])
        self.assertTrue(is_server(s["command"][0]))
        self.assertEqual(s["selector"], "source.c")
        p = load_json("sublime", "basilisk.sublime-project")["settings"]["LSP"]
        self.assertEqual(p["clangd"], {"enabled": False})

    def test_coc(self):
        s = load_json("coc", "coc-settings.json")["languageserver"]["basilisk"]
        self.assertTrue(is_server(s["command"]))
        self.assertEqual(s["filetypes"], ["basilisk"])

    @unittest.skipUnless(shutil.which("vim"), "vim not installed")
    def test_ale_linter(self):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "autoload", "ale"))
        with open(os.path.join(tmp, "autoload", "ale", "linter.vim"), "w") as f:
            f.write("function! ale#linter#Define(filetype, linter) abort\n"
                    "  let g:defined = [a:filetype, a:linter]\nendfunction\n")
        case = os.path.join(tmp, "case")
        os.makedirs(os.path.join(case, "sub"))
        open(os.path.join(case, ".basilisk-lsp.json"), "w").close()
        src = os.path.join(case, "sub", "x.c")
        out = os.path.join(tmp, "out.json")
        script = os.path.join(tmp, "t.vim")
        with open(script, "w") as f:
            f.write(f"set rtp^={tmp}\nset rtp^={ROOT}\nruntime! ale_linters/basilisk/*.vim\n"
                    f"edit {src}\nlet L = g:defined[1]\n"
                    "call writefile([json_encode({'ft': g:defined[0], 'name': L.name, 'lsp': L.lsp, "
                    "'command': L.command, 'exe': call(L.executable, [bufnr('')]), "
                    "'root': call(L.project_root, [bufnr('')])})], " + json.dumps(out) + ")\nqa!\n")
        subprocess.run(["vim", "-N", "-u", "NONE", "-i", "NONE", "-es", "-S", script],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        with open(out) as f:
            r = json.load(f)
        self.assertEqual((r["ft"], r["name"], r["lsp"], r["command"]), ("basilisk", "basilisk_lsp", "stdio", "%e"))
        self.assertEqual(r["exe"], os.path.join(ROOT, "bin", "basilisk-lsp"))
        self.assertEqual(os.path.realpath(r["root"]), os.path.realpath(case))


if __name__ == "__main__":
    unittest.main(verbosity=2)
