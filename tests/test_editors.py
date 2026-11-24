#!/usr/bin/env python3
"""Headless editor tests: vim, neovim, Emacs and nano, each skipped when
the editor (or a recent enough version) is not installed. Every editor
runs with an empty $HOME and loads this repository like a user would.
Parts which need qcc run only when Basilisk is available."""
import json, os, re, shutil, subprocess, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
FIX = os.path.join(HERE, "fixtures", "editors")
SAMPLE = os.path.join(FIX, "sample.c")
PLAIN = os.path.join(FIX, "plain.c")
BAD = os.path.join(HERE, "fixtures", "diagnostics", "parse_errors", "case.c")

sys.path.insert(0, os.path.join(ROOT, "server"))
import basilisk_lsp  # noqa: E402

_cfg = basilisk_lsp.Server().config(BAD)
HAVE_BASILISK = bool(_cfg["root"] and _cfg["qccExe"])


def version(cmd, regex):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(regex, out)
    return tuple(int(x) for x in m.groups()) if m else None


def fresh_home():
    home = tempfile.mkdtemp(prefix="editor-home-")
    return home, dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
                      XDG_DATA_HOME=os.path.join(home, ".local", "share"),
                      XDG_STATE_HOME=os.path.join(home, ".local", "state"),
                      XDG_CACHE_HOME=os.path.join(home, ".cache"))


def link_package(home, *parts):
    d = os.path.join(home, *parts)
    os.makedirs(d, exist_ok=True)
    os.symlink(ROOT, os.path.join(d, "basilisk-editor"))


# ---------------------------------------------------------------------------

@unittest.skipUnless(shutil.which("vim"), "vim not installed")
class Vim(unittest.TestCase):
    GROUPS = {  # search pattern: syntax group expected at the match
        r"# Sample": "basiliskDocHeading", r"\*emph\*": "basiliskDocEmph",
        r"\<face\>": "basiliskStorage", r"\<vector\>": "basiliskType",
        r"^event": "basiliskStatement", r"event \zsinit": "basiliskEventName",
        r"\<end\>": "basiliskEventCond", r"\<foreach\>": "basiliskRepeat",
        r"\<reduction\>": "basiliskStatement", r"\[\]": "basiliskStencil",
        r"\.x": "basiliskComponent", r"\<Delta\>": "basiliskBuiltin",
    }

    def run_vim(self, script_lines):
        home, env = fresh_home()
        link_package(home, ".vim", "pack", "test", "start")
        with open(os.path.join(home, ".vimrc"), "w") as f:
            f.write("filetype plugin indent on\nsyntax on\n")
        out = os.path.join(home, "out.json")
        script = os.path.join(home, "t.vim")
        with open(script, "w") as f:
            f.write("\n".join(script_lines).replace("OUT", out) + "\nqa!\n")
        subprocess.run(["vim", "-N", "-u", os.path.join(home, ".vimrc"), "-i", "NONE", "-es", "-S", script],
                       env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
        with open(out) as f:
            return json.load(f)

    def test_detection_and_syntax(self):
        lines = [f"edit {PLAIN}", "let r = {'plain': &filetype}", f"edit {SAMPLE}",
                 "let r.ft = &filetype", "let r.makeprg = &makeprg", "let r.groups = {}"]
        for pat in self.GROUPS:
            lines += ["call cursor(1, 1)", f"let p = searchpos({json.dumps(pat)}, 'cW')",
                      f"let r.groups[{json.dumps(pat)}] = synIDattr(synID(p[0], p[1], 1), 'name')"]
        lines.append("call writefile([json_encode(r)], 'OUT')")
        r = self.run_vim(lines)
        self.assertEqual(r["plain"], "c")
        self.assertEqual(r["ft"], "basilisk")
        self.assertIn(os.path.join(ROOT, "bin", "basilisk-lsp"), r["makeprg"])
        self.assertEqual(r["groups"], self.GROUPS)

    @unittest.skipUnless(HAVE_BASILISK, "Basilisk (qcc) not available")
    def test_make_quickfix(self):
        r = self.run_vim([f"edit {BAD}", "silent make", "let q = getqflist()",
                          "call writefile([json_encode(map(q, {_, e -> [e.lnum, e.type]}))], 'OUT')"])
        self.assertEqual(len(r), 6)
        self.assertEqual(r[0], [6, "w"])


NVIM = version(["nvim", "--version"], r"NVIM v(\d+)\.(\d+)") if shutil.which("nvim") else None


@unittest.skipUnless(NVIM and NVIM >= (0, 11), "neovim >= 0.11 not installed")
class Neovim(unittest.TestCase):
    def test_lsp(self):
        home, env = fresh_home()
        link_package(home, ".local", "share", "nvim", "site", "pack", "test", "start")
        out = os.path.join(home, "out.json")
        script = os.path.join(home, "t.lua")
        with open(script, "w") as f:
            f.write(f'''
local r = {{}}
vim.cmd('edit {PLAIN}'); r.plain = vim.bo.filetype
vim.cmd('edit {SAMPLE}'); r.ft = vim.bo.filetype
vim.wait(20000, function() local c = vim.lsp.get_clients({{bufnr = 0}}); return #c > 0 and c[1].initialized end)
local c = vim.lsp.get_clients({{bufnr = 0}})[1]
r.client = c and c.name or 'none'
if c then
  local pos = vim.fn.searchpos('foreach', 'nw')
  local h = c:request_sync('textDocument/hover', {{textDocument = {{uri = vim.uri_from_bufnr(0)}},
    position = {{line = pos[1] - 1, character = pos[2]}}}}, 10000, 0)
  r.hover = h and h.result and h.result.contents.value or ''
end
if {str(HAVE_BASILISK).lower()} then
  vim.cmd('edit {BAD}')
  vim.wait(60000, function() return #vim.diagnostic.get(0) > 0 end)
  r.diagnostics = #vim.diagnostic.get(0)
end
vim.fn.writefile({{vim.json.encode(r)}}, '{out}')
vim.cmd('qa!')
''')
        subprocess.run(["nvim", "--headless", "-c", f"luafile {script}"], env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
        with open(out) as f:
            r = json.load(f)
        self.assertEqual(r["plain"], "c")
        self.assertEqual(r["ft"], "basilisk")
        self.assertEqual(r["client"], "basilisk")
        self.assertIn("leaf cells", r["hover"])
        if HAVE_BASILISK:
            self.assertEqual(r["diagnostics"], 6)


EMACS = version(["emacs", "--version"], r"GNU Emacs (\d+)\.(\d+)") if shutil.which("emacs") else None


@unittest.skipUnless(EMACS and EMACS >= (29, 1), "Emacs >= 29.1 not installed")
class Emacs(unittest.TestCase):
    FACES = {"^event": "font-lock-keyword-face", "event \\(init\\)": "font-lock-function-name-face",
             "foreach": "font-lock-keyword-face", "\\_<vector\\_>": "font-lock-type-face",
             "\\_<face\\_>": "font-lock-keyword-face", "Delta": "font-lock-builtin-face",
             "\\_<end\\_>": "font-lock-constant-face"}

    def test_mode_faces_eglot(self):
        home, env = fresh_home()
        out = os.path.join(home, "out.json")
        faces = " ".join(f"({json.dumps(k)} . {1 if chr(92) + '(' in k else 0})" for k in self.FACES)
        el = f'''
(add-to-list 'load-path {json.dumps(ROOT)})
(require 'basilisk-editor)
(require 'json)
(require 'eglot)
(setq basilisk-auto-lsp nil)
(let ((r nil))
  (find-file {json.dumps(PLAIN)}) (push (cons "plain" (symbol-name major-mode)) r)
  (find-file {json.dumps(SAMPLE)}) (font-lock-ensure)
  (push (cons "mode" (symbol-name major-mode)) r)
  (push (cons "faces"
              (mapcar (lambda (e)
                        (goto-char (point-min)) (re-search-forward (car e))
                        (let ((f (get-text-property (match-beginning (cdr e)) 'face)))
                          (cons (car e) (symbol-name (if (listp f) (car f) f)))))
                      '({faces})))
        r)
  (apply #'eglot--connect (eglot--guess-contact))
  (let ((srv (eglot-current-server)))
    (push (cons "server" (if srv "yes" "no")) r)
    (goto-char (point-min)) (search-forward "foreach") (backward-char 2)
    (push (cons "hover" (plist-get (plist-get (jsonrpc-request srv :textDocument/hover
                                                              (eglot--TextDocumentPositionParams))
                                              :contents) :value)) r))
  (when {"t" if HAVE_BASILISK else "nil"}
    (find-file {json.dumps(BAD)})
    (apply #'eglot--connect (eglot--guess-contact))
    ;; batch mode: flymake waits for the buffer to be displayed; start it
    (flymake-start)
    (with-timeout (60) (while (= 0 (length (flymake-diagnostics))) (accept-process-output nil 0.5)))
    (push (cons "diagnostics" (length (flymake-diagnostics))) r))
  (with-temp-file {json.dumps(out)} (insert (json-encode r))))
(kill-emacs 0)
'''
        script = os.path.join(home, "t.el")
        with open(script, "w") as f:
            f.write(el)
        subprocess.run(["emacs", "-Q", "--batch", "-l", script], env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
        with open(out) as f:
            r = json.load(f)
        self.assertEqual(r["plain"], "c-mode")
        self.assertEqual(r["mode"], "basilisk-c-mode")
        self.assertEqual(r["faces"], self.FACES)
        self.assertEqual(r["server"], "yes")
        self.assertIn("leaf cells", r["hover"])
        if HAVE_BASILISK:
            self.assertEqual(r["diagnostics"], 6)

    def test_byte_compiles_cleanly(self):
        tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(ROOT, "basilisk-editor.el"), tmp)
        r = subprocess.run(["emacs", "-Q", "--batch", "--eval", "(setq byte-compile-error-on-warn t)",
                            "-f", "batch-byte-compile", os.path.join(tmp, "basilisk-editor.el")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipUnless(shutil.which("nano") and shutil.which("tmux"), "nano or tmux not installed")
class Nano(unittest.TestCase):
    def screen(self, path, keys=(), wait=1.0):
        home, env = fresh_home()
        bindir = os.path.join(home, "bin")
        os.makedirs(bindir)
        os.symlink(os.path.join(ROOT, "bin", "basilisk-lsp"), os.path.join(bindir, "basilisk-lsp"))
        rc = os.path.join(home, "nanorc")
        with open(rc, "w") as f:
            f.write(f'include "{os.path.join(ROOT, "nano", "basilisk.nanorc")}"\n')
        session = "basilisk-test-%d" % os.getpid()
        cmd = (f"cd {os.path.dirname(path)} && HOME={home} PATH={bindir}:$PATH TERM=xterm-256color "
               f"nano --rcfile={rc} {os.path.basename(path)}; sleep 5")
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-x", "150", "-y", "14", cmd], env=env, check=True)
        try:
            time.sleep(1.0)
            for k in keys:
                subprocess.run(["tmux", "send-keys", "-t", session, k], check=True)
                time.sleep(0.5)
            time.sleep(wait)
            return subprocess.run(["tmux", "capture-pane", "-e", "-p", "-t", session],
                                  capture_output=True, text=True).stdout
        finally:
            subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)

    def test_highlighting(self):
        s = self.screen(SAMPLE)
        self.assertRegex(s, r"\x1b\[[0-9;]*m(\x1b\[[0-9;]*m)*event")      # coloured
        self.assertRegex(s, r"\x1b\[[0-9;]*m(\x1b\[[0-9;]*m)*foreach")
        self.assertRegex(s, r"\x1b\[[0-9;]*m(\x1b\[[0-9;]*m)*Delta")

    @unittest.skipUnless(HAVE_BASILISK, "Basilisk (qcc) not available")
    def test_linter(self):
        s = self.screen(BAD, keys=("C-t", "C-y"), wait=8)
        self.assertIn("Linting", s)
        self.assertIn("parse error", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
