#!/usr/bin/env python3
"""
Basilisk C language server.

A dependency-free (Python >= 3.8 stdlib only) Language Server Protocol
implementation for Basilisk C (http://basilisk.fr).

Features
  - diagnostics, by running `qcc -fsyntax-only` on the (unsaved) buffer
  - completion: Basilisk keywords/snippets, symbols from the headers
    the file includes (transitively), #include paths, .x/.y/.z
  - hover: signature + the literate /** ... */ documentation
  - go to definition (into Basilisk headers, #include lines)
  - document symbols (events, functions, fields, macros)

Copyright (C) 2026 the basilisk-editor contributors.
Licensed under the GNU GPL, version 3 or later (see LICENSE), like Basilisk.

Usage
  basilisk_lsp.py [--stdio]             run the language server on stdio
  basilisk_lsp.py --lint FILE [FLAGS]   print diagnostics as FILE:LINE:COL: sev: msg
  basilisk_lsp.py --config FILE         show the settings which apply to FILE

Settings (lowest to highest precedence): built-in defaults, editor
settings (LSP initializationOptions / workspace configuration), and the
project file `.basilisk-lsp.json`, looked up from the file's directory
upwards. See README.md.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

VERSION = "0.1.0"

DEFAULTS = {
    "qcc": "qcc",              # qcc executable (found in basiliskPath if not on PATH)
    "qccFlags": ["-Wall"],     # extra flags for diagnostics (e.g. -grid=octree)
    "includeDirs": [],         # extra include directories (-I)
    "diagnostics": "onChange", # "onChange" | "onSave" | "off"
    "debounce": 1.0,           # seconds, for onChange
    "basiliskPath": None,      # Basilisk's src/ directory ($BASILISK)
}
PROJECT_FILE = ".basilisk-lsp.json"
# where Basilisk usually lives when neither $BASILISK nor qcc's PATH say
COMMON_ROOTS = ["~/basilisk/src", "~/basilisk/basilisk/src", "~/src/basilisk/src",
                "/usr/local/basilisk/src", "/opt/basilisk/src"]


def log(*args):
    print("[basilisk-lsp]", *args, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Configuration

def is_root(d):
    return bool(d) and os.path.isfile(os.path.join(d, "common.h"))


def find_project_file(path):
    d = os.path.dirname(os.path.abspath(path))
    while True:
        f = os.path.join(d, PROJECT_FILE)
        if os.path.isfile(f):
            return f
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


_project_cache = {}


def load_project_file(f):
    """Returns (settings, error)."""
    try:
        mt = os.stat(f).st_mtime
    except OSError as e:
        return {}, str(e)
    c = _project_cache.get(f)
    if c and c[0] == mt:
        return c[1], c[2]
    try:
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        unknown = sorted(set(data) - set(DEFAULTS))
        err = f"{f}: unknown setting(s) {', '.join(unknown)}" if unknown else None
        res = ({k: v for k, v in data.items() if k in DEFAULTS}, err)
    except (OSError, ValueError) as e:
        res = ({}, f"{f}: {e}")
    _project_cache[f] = (mt,) + res
    return res


def absolutize(settings, base):
    """Makes the relative paths in `settings` relative to directory `base`."""
    s = dict(settings)
    flags = s.get("qccFlags")
    if isinstance(flags, str):
        flags = flags.split()
    if flags is not None:
        out = []
        for fl in flags:
            if fl.startswith("-I") and len(fl) > 2:
                fl = "-I" + os.path.normpath(os.path.join(base, os.path.expanduser(fl[2:])))
            out.append(fl)
        s["qccFlags"] = out
    if s.get("includeDirs") is not None:
        s["includeDirs"] = [os.path.normpath(os.path.join(base, os.path.expanduser(d)))
                            for d in s["includeDirs"]]
    for k in ("basiliskPath", "qcc"):
        v = s.get(k)
        if v and (os.sep in v or v.startswith("~")):
            s[k] = os.path.normpath(os.path.join(base, os.path.expanduser(v)))
    return s


def find_basilisk(cfg):
    """Returns (root or None, list of what was tried)."""
    tried = []
    cands = [("setting basiliskPath", cfg.get("basiliskPath")),
             ("$BASILISK", os.environ.get("BASILISK"))]
    q = shutil.which(cfg.get("qcc") or "qcc")
    cands.append(("qcc on PATH", os.path.dirname(os.path.realpath(q)) if q else None))
    cands += [("common location", os.path.expanduser(c)) for c in COMMON_ROOTS]
    for what, d in cands:
        if not d:
            continue
        tried.append(f"{what} ({d})")
        if is_root(d):
            return os.path.abspath(d), tried
    return None, tried


def resolve_config(settings, path):
    """Effective configuration for file `path`, given the editor `settings`."""
    cfg = dict(DEFAULTS)
    doc_dir = os.path.dirname(os.path.abspath(path))
    cfg.update({k: v for k, v in absolutize(settings, doc_dir).items() if v is not None})
    errors = []
    proj = find_project_file(path)
    if proj:
        data, err = load_project_file(proj)
        if err:
            errors.append(err)
        cfg.update({k: v for k, v in absolutize(data, os.path.dirname(proj)).items() if v is not None})
    cfg["project"] = proj
    root, tried = find_basilisk(cfg)
    cfg["root"] = root
    qcc = shutil.which(cfg.get("qcc") or "qcc")
    if not qcc and root and os.path.isfile(os.path.join(root, "qcc")):
        qcc = os.path.join(root, "qcc")
    cfg["qccExe"] = qcc
    flags = list(cfg.get("qccFlags") or [])
    flags += ["-I" + d for d in cfg.get("includeDirs") or []]
    cfg["flags"] = flags
    cfg["idirs"] = [f[2:] for f in flags if f.startswith("-I") and len(f) > 2]
    if not root:
        errors.append("cannot find Basilisk (tried: " + "; ".join(tried) + "). Set $BASILISK, "
                      "put qcc on PATH, or set basiliskPath in " + PROJECT_FILE + " or the editor settings.")
    elif not qcc:
        errors.append(f"cannot find qcc (not on PATH nor in {root}); set the `qcc` setting.")
    cfg["errors"] = errors
    cfg["key"] = json.dumps({k: cfg[k] for k in ("root", "flags", "qccExe", "project")}, sort_keys=True)
    return cfg


# ---------------------------------------------------------------------------
# Lexical helpers

ID = r"[A-Za-z_]\w*"
BLANK = re.compile(r"[^\n]")
TOKENS = re.compile(
    r"/\*.*?(?:\*/|\Z)"                 # block comment
    r"|//[^\n]*"                        # line comment
    r'|"(?:\\.|[^"\\\n])*"?'            # string
    r"|'(?:\\.|[^'\\\n])*'?",           # char
    re.S)


def blank_comments(text):
    """Returns (code, blocks, trailing).

    code: text with comments and string contents replaced by spaces
          (newlines preserved, so line/column positions are unchanged).
    blocks: {end_line: (start_line, comment)} for block comments.
    trailing: {line: comment} for comments that follow code on a line."""
    blocks, trailing = {}, {}
    parts, last, line = [], 0, 0
    for m in TOKENS.finditer(text):
        s = m.group()
        line += text.count("\n", last, m.start())
        parts.append(text[last:m.start()])
        if s.startswith("/*") or s.startswith("//"):
            end = line + s.count("\n")
            bol = text.rfind("\n", 0, m.start()) + 1
            if text[bol:m.start()].strip():
                trailing[line] = s
            elif s.startswith("/*"):
                blocks[end] = (line, s)
            else:
                blocks[end] = (line, s)
            parts.append(BLANK.sub(" ", s))
        else:
            q = s[0]
            closed = len(s) > 1 and s[-1] == q
            inner = s[1:-1] if closed else s[1:]
            parts.append(q + BLANK.sub(" ", inner) + (q if closed else ""))
        line += s.count("\n")
        last = m.end()
    parts.append(text[last:])
    return "".join(parts), blocks, trailing


def clean_comment(c):
    """Turns a raw C comment into (markdown) text."""
    if c.startswith("//"):
        return "\n".join(l.strip()[2:].strip() for l in c.splitlines())
    c = re.sub(r"^/\*+", "", c)
    c = re.sub(r"\*+/$", "", c)
    lines = c.split("\n")
    # strip " * " prefixes when every line has one
    body = [l for l in lines[1:] if l.strip()]
    if body and all(l.lstrip().startswith("*") for l in body):
        lines = [lines[0]] + [re.sub(r"^\s*\* ?", "", l) for l in lines[1:]]
    # dedent
    ind = [len(l) - len(l.lstrip()) for l in lines[1:] if l.strip()]
    if ind:
        n = min(ind)
        lines = [lines[0]] + [l[n:] for l in lines[1:]]
    out = "\n".join(lines).strip()
    if len(out) > 3000:
        out = out[:3000].rstrip() + "\n\n…"
    return out


def collect_parens(lines, ln, col, maxlines=80):
    """lines[ln][col] == '('. Returns (end_ln, end_col) just after the
    matching ')' or None."""
    depth = 0
    for l in range(ln, min(len(lines), ln + maxlines)):
        s = lines[l]
        for c in range(col if l == ln else 0, len(s)):
            ch = s[c]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    return l, c + 1
    return None


def next_char(lines, ln, col, maxlines=8):
    """First non-blank character at or after (ln, col)."""
    for l in range(ln, min(len(lines), ln + maxlines)):
        s = lines[l][col if l == ln else 0:].lstrip()
        if s:
            return s[0]
    return ""


def span_text(lines, ln, col, eln, ecol):
    if ln == eln:
        return lines[ln][col:ecol]
    return "\n".join([lines[ln][col:]] + lines[ln + 1:eln] + [lines[eln][:ecol]])


def squash(s, n=160):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    return s if len(s) <= n else s[:n - 1] + "…"


def split_top(s, sep=","):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


# ---------------------------------------------------------------------------
# Symbol scanner

NOT_TYPES = {"if", "for", "while", "switch", "return", "else", "do", "case",
             "goto", "sizeof", "typedef", "event", "macro", "break",
             "continue", "default", "foreach", "foreach_dimension", "struct",
             "union", "enum", "trace", "delete"}

RE_INCLUDE = re.compile(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]')
RE_DEFINE = re.compile(r"^\s*#\s*define\s+(" + ID + r")(\([^)]*\))?(.*)$")
RE_EVENT = re.compile(r"^event\s+(" + ID + r")\s*\(")
RE_MACRO = re.compile(r"^macro\d*\s+(?:.*?[\s\*])?(" + ID + r")\s*\(")
RE_FIELD = re.compile(
    r"^((?:\(const\)\s*|const\s+|static\s+|extern\s+)*"
    r"(?:(?:face|vertex|symmetric)\s+)?(?:scalar|vector|tensor))\b(.*)$")
RE_FUNC = re.compile(r"^((?:" + ID + r"[\s\*]+)*?)(" + ID + r")\s*\(")
RE_STRUCT = re.compile(r"^(?:typedef\s+)?(struct|union|enum)\s+(" + ID + r")\s*\{")
RE_TYPEDEF_OPEN = re.compile(r"^typedef\s+(struct|union|enum)\b[^;]*\{")
RE_TYPEDEF_END = re.compile(r"^\}\s*(" + ID + r")\s*;")
RE_TYPEDEF_LINE = re.compile(r"^typedef\s+[^;{]*?\b(" + ID + r")\s*(?:\[[^\]]*\])?\s*;")
RE_GLOBAL = re.compile(
    r"^((?:(?:static|extern|const|unsigned|signed|long|short)\s+)*" + ID +
    r")([\s\*]+)(" + ID + r")\s*(\[[^\]]*\])?\s*(=|;|,)")


class Symbol:
    __slots__ = ("name", "kind", "sig", "doc", "path", "line", "col", "ftype")

    def __init__(self, name, kind, sig, doc, path, line, col, ftype=None):
        self.name, self.kind, self.sig, self.doc = name, kind, sig, doc
        self.path, self.line, self.col, self.ftype = path, line, col, ftype


class FileInfo:
    def __init__(self, symbols, includes, title):
        self.symbols = symbols    # list of Symbol
        self.includes = includes  # list of (delim, name, line)
        self.title = title


def scan(text, path):
    code, blocks, trailing = blank_comments(text)
    lines = code.split("\n")
    orig = text.split("\n")
    syms, includes = [], []

    def doc_for(start, line=None):
        if line is not None and line in trailing:
            return clean_comment(trailing[line])
        k = start - 1
        while k >= 0:
            if k in blocks:
                return clean_comment(blocks[k][1])
            s = lines[k].strip()
            if s and s != "trace":
                return ""
            k -= 1
        return ""

    def add(name, kind, sig, ln, start=None, ftype=None):
        col = orig[ln].find(name) if ln < len(orig) else 0
        syms.append(Symbol(name, kind, sig, doc_for(ln if start is None else start, ln),
                           path, ln, max(col, 0), ftype))

    typedef_start = None
    title = ""
    first_block = min(blocks) if blocks else None
    if first_block is not None:
        c = clean_comment(blocks[first_block][1])
        m = re.search(r"^#+\s*(.+)$", c, re.M)
        title = m.group(1).strip() if m else squash(c.split("\n\n")[0], 100)

    for ln, line in enumerate(lines):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            m = RE_INCLUDE.match(orig[ln])
            if m:
                includes.append((m.group(1), m.group(2).strip(), ln))
                continue
            m = RE_DEFINE.match(orig[ln])
            if m:
                body = m.group(3).rstrip().rstrip("\\").strip()
                sig = "#define " + m.group(1) + (m.group(2) or "") + (" " + body if body else "")
                add(m.group(1), "define", squash(sig, 120), ln)
            continue
        if line[0].isspace():
            continue

        m = RE_EVENT.match(line)
        if m:
            p = collect_parens(lines, ln, line.index("(", m.end(1)))
            sig = "event " + m.group(1) + " " + (
                squash(span_text(lines, ln, line.index("(", m.end(1)), *p)) if p else "()")
            add(m.group(1), "event", sig, ln)
            continue

        m = RE_MACRO.match(line)
        if m:
            i = line.index("(", m.end(1))
            p = collect_parens(lines, ln, i)
            sig = squash(span_text(lines, ln, 0, *p) if p else line)
            add(m.group(1), "macro", sig, ln)
            continue

        m = RE_STRUCT.match(line)
        if m:
            add(m.group(2), "type", m.group(1) + " " + m.group(2), ln)
            if line.startswith("typedef"):
                typedef_start = ln
            continue
        if RE_TYPEDEF_OPEN.match(line):
            typedef_start = ln
            continue
        m = RE_TYPEDEF_END.match(line)
        if m:
            start = typedef_start if typedef_start is not None else ln
            add(m.group(1), "type", "typedef " + m.group(1), ln, start)
            typedef_start = None
            continue
        m = RE_TYPEDEF_LINE.match(line)
        if m:
            add(m.group(1), "type", squash(orig[ln], 120), ln)
            continue

        m = RE_FUNC.match(line)
        if m and m.group(2) not in NOT_TYPES:
            words = m.group(1).split()
            start = ln
            ok = bool(words) and words[0] not in NOT_TYPES
            if not words and ln > 0:
                prev = lines[ln - 1]
                if (prev.strip() and not prev[0].isspace() and
                        re.match(r"^[\w\s\*]+$", prev) and
                        prev.split()[0] not in NOT_TYPES):
                    ok, start = True, ln - 1
            if ok:
                i = line.index("(", m.end(2))
                p = collect_parens(lines, ln, i)
                if p:
                    nc = next_char(lines, p[0], p[1])
                    if nc in "{;" or nc.isalpha():
                        sig = squash(span_text(lines, start, 0, *p))
                        kind = "function" if nc != ";" else "prototype"
                        add(m.group(2), kind, sig, ln, start)
                continue

        m = RE_FIELD.match(line)
        if m:
            ftype = re.sub(r"\s+", " ", m.group(1)).strip()
            stmt = m.group(2)
            k = ln
            while ";" not in stmt and k + 1 < len(lines) and k < ln + 10:
                k += 1
                stmt += "\n" + lines[k]
            stmt = stmt.split(";")[0]
            for item in split_top(stmt):
                mm = re.match(r"\s*(\*?)\s*(" + ID + r")\s*(\[[^\]]*\])?", item)
                if not mm:
                    continue
                t = ftype + (" *" if mm.group(1) else "")
                sig = t + " " + mm.group(2) + (mm.group(3) or "")
                rest = item[mm.end():].strip()
                if rest.startswith("="):
                    sig += " " + squash(rest, 60)
                add(mm.group(2), "field", sig, ln, ftype=t)
            continue

        m = RE_GLOBAL.match(line)
        if m and m.group(1).split()[0] not in NOT_TYPES:
            sig = squash(orig[ln].split(";")[0].split("{")[0], 120).rstrip(" =")
            add(m.group(3), "variable", sig, ln, ftype=m.group(1) + m.group(2).strip())

    # drop prototypes when a definition exists in the same file
    defined = {s.name for s in syms if s.kind == "function"}
    out, seen = [], set()
    for s in syms:
        if s.kind == "prototype":
            if s.name in defined:
                continue
            s.kind = "function"
        key = (s.name, s.kind)
        if key in seen and s.kind != "event":
            continue
        seen.add(key)
        out.append(s)
    return FileInfo(out, includes, title)


# ---------------------------------------------------------------------------
# Built-in Basilisk constructs

# GENERATED by tools/generate.py from spec/language.json -- do not edit
# kind, signature, markdown documentation of built-in Basilisk constructs
BUILTINS = {
    "foreach": ("keyword", "foreach (reduction(op:var) ...) statement",
        "Loops over all the leaf cells of the grid (in parallel with OpenMP/MPI).\n\nInside the loop: `x`, `y`, `z` are the coordinates of the cell centre, `Delta` is the cell size, `point` the current `Point`, and fields are accessed through stencils: `s[]`, `s[1]`, `s[-1,0]`, `s[0,1]`...\n\nGlobal accumulations must be declared with `reduction(+:sum)` (also `min`, `max`)."),
    "foreach_face": ("keyword", "foreach_face (x|y|z, reduction(...)) statement",
        "Loops over the faces of the leaf cells. The body is written for the *x* direction and automatically rotated for the other directions (as with `foreach_dimension()`); `foreach_face(x)` restricts the loop to the *x* faces. Use it to update `face vector` fields: `uf.x[]` is the value on the face between `[-1]` and `[]`."),
    "foreach_vertex": ("keyword", "foreach_vertex () statement",
        "Loops over the vertices of the leaf cells (for `vertex` fields)."),
    "foreach_dimension": ("keyword", "foreach_dimension () statement",
        "Repeats the following statement (or function definition) for each dimension, rotating `x`→`y`→`z` in component names (`.x`, `_x`) and stencil indices."),
    "foreach_level": ("keyword", "foreach_level (int l) statement",
        "Loops over all the cells at level `l` of the tree."),
    "foreach_level_or_leaf": ("keyword", "foreach_level_or_leaf (int l) statement",
        "Loops over the cells at level `l` and the leaf cells coarser than `l`."),
    "foreach_coarse_level": ("keyword", "foreach_coarse_level (int l) statement",
        "Loops over the non-leaf cells at level `l`."),
    "foreach_leaf": ("keyword", "foreach_leaf () statement",
        "Loops over the leaf cells (equivalent to `foreach()`)."),
    "foreach_cell": ("keyword", "foreach_cell () statement",
        "Depth-first traversal of the whole tree, starting from the root. Use `continue` to skip the children of the current cell and `is_leaf(cell)` to detect leaves."),
    "foreach_child": ("keyword", "foreach_child () statement",
        "Loops over the children of the current cell."),
    "foreach_neighbor": ("keyword", "foreach_neighbor (int n = 2) statement",
        "Loops over the neighbours of the current cell, within a stencil of half-width `n`."),
    "foreach_boundary": ("keyword", "foreach_boundary (int b) statement",
        "Loops over the cells adjacent to boundary `b` (e.g. `left`)."),
    "foreach_point": ("keyword", "foreach_point (double x, double y, double z) statement",
        "Executes the statement on the leaf cell containing the point (x, y, z)."),
    "foreach_fine_to_coarse": ("keyword", "foreach_fine_to_coarse () statement",
        "Loops over the non-leaf cells, from the finest to the coarsest level."),
    "foreach_block": ("keyword", "foreach_block () statement",
        "Loops over the blocks/layers of block data (multilayer solver)."),
    "foreach_layer": ("keyword", "foreach_layer () statement",
        "Loops over the layers (multilayer solver). Inside, `point.l` is the layer index."),
    "event": ("keyword", "event name (condition; ...) { ... }",
        "Defines an event, executed by `run()` when its conditions are met.\n\nConditions: `i = 0`, `i++`, `i += 10`, `t = 0`, `t += 0.1`, `t <= 10`, `t = end`, `first`, `last`, `t = {0, 1, 2}`... Events with the same name as an existing event (e.g. `init`, `logfile`, `adapt`) are added to it; returning 1 stops the run."),
    "reduction": ("keyword", "reduction (op : var)",
        "Declares a parallel reduction for a `foreach` loop. `op` is `+`, `min` or `max`; `var` is a variable or an array `var[:n]`."),
    "scalar": ("type", "scalar s[];",
        "A scalar field. Global or local declarations `scalar s[];` allocate the field (local fields are freed automatically at the end of the scope); `scalar s = new scalar;` allocates dynamically. Values are accessed inside `foreach` loops as `s[]`, `s[1,0]`..."),
    "vector": ("type", "vector u[];",
        "A vector field, with components `u.x`, `u.y` (and `u.z`)."),
    "tensor": ("type", "tensor T[];",
        "A tensor field, with components `T.x.x`, `T.x.y`, ..."),
    "face": ("keyword", "face vector uf[];",
        "Qualifier: a `face vector` is staggered on cell faces (`uf.x[]` lives on the face between `[-1]` and `[]`)."),
    "vertex": ("keyword", "vertex scalar s[];",
        "Qualifier: a `vertex scalar` is defined on cell vertices."),
    "symmetric": ("keyword", "symmetric tensor T[];",
        "Qualifier: a symmetric tensor (`T.x.y` and `T.y.x` share storage)."),
    "new": ("keyword", "new scalar | new vector | new face vector ...",
        "Dynamically allocates a new field; free it with `delete ({s});`."),
    "delete": ("function", "void delete (scalar * list)",
        "Frees the fields in `list`."),
    "trace": ("keyword", "trace",
        "Marks the following function for profiling (`-DTRACE`)."),
    "macro": ("keyword", "macro [type] name (args) { ... }",
        "Basilisk macro: a function-like definition inlined by qcc, which can take a code block as its last argument."),
    "Delta": ("variable", "double Delta",
        "Size of the current cell (inside `foreach`-type loops)."),
    "x": ("variable", "double x",
        "*x*-coordinate of the current cell (or face) centre."),
    "y": ("variable", "double y",
        "*y*-coordinate of the current cell (or face) centre."),
    "z": ("variable", "double z",
        "*z*-coordinate of the current cell (or face) centre."),
    "t": ("variable", "double t",
        "Physical time."),
    "dt": ("variable", "double dt",
        "Current timestep."),
    "i": ("variable", "int i",
        "Iteration (timestep) counter."),
    "point": ("variable", "Point point",
        "The current cell, inside `foreach`-type loops."),
    "level": ("variable", "int level",
        "Level of the current cell (inside loops)."),
    "dimension": ("define", "dimension",
        "Number of space dimensions (1, 2 or 3)."),
    "val": ("macro", "val (s, i, j, k)",
        "Explicit stencil access, equivalent to `s[i,j,k]`."),
    "fine": ("macro", "fine (s, i, j, k)",
        "Value of field `s` in child cell (i, j, k)."),
    "coarse": ("macro", "coarse (s, i, j, k)",
        "Value of field `s` in the parent cell."),
    "neighbor": ("macro", "neighbor (i, j, k)",
        "The neighbouring `Point` at offset (i, j, k)."),
    "left": ("variable", "left",
        "Left boundary (e.g. `u.n[left] = dirichlet(0);`)."),
    "right": ("variable", "right",
        "Right boundary."),
    "top": ("variable", "top",
        "Top boundary."),
    "bottom": ("variable", "bottom",
        "Bottom boundary."),
    "front": ("variable", "front",
        "Front boundary (3D)."),
    "back": ("variable", "back",
        "Back boundary (3D)."),
    "in": ("keyword", "for (scalar s in list)",
        "Iterates over the fields of a list."),
    "first": ("keyword", "first",
        "Event condition: first."),
    "last": ("keyword", "last",
        "Event condition: last (executed after all other events of the same name)."),
    "end": ("keyword", "t = end",
        "Event condition: the end of the run."),
}

SNIPPETS = {
    "foreach": "foreach() {\n\t$0\n}",
    "foreach_face": "foreach_face() {\n\t$0\n}",
    "foreach_vertex": "foreach_vertex() {\n\t$0\n}",
    "foreach_dimension": "foreach_dimension()\n\t$0",
    "foreach_level": "foreach_level(${1:l}) {\n\t$0\n}",
    "foreach_neighbor": "foreach_neighbor(${1:1}) {\n\t$0\n}",
    "foreach_child": "foreach_child() {\n\t$0\n}",
    "foreach_boundary": "foreach_boundary(${1:left}) {\n\t$0\n}",
    "event": "event ${1:name} (${2:i++}) {\n\t$0\n}",
    "reduction": "reduction(${1|+,min,max|}:${2:var})",
}
# END GENERATED

C_KEYWORDS = ("auto break case char const continue default do double else enum "
              "extern float for goto if inline int long register restrict return "
              "short signed sizeof static struct switch typedef union unsigned "
              "void volatile while bool true false NULL coord Point").split()

STDLIB = ("sqrt cbrt exp log log10 pow sin cos tan asin acos atan atan2 sinh cosh "
          "tanh fabs floor ceil round fmod fmin fmax hypot erf printf fprintf "
          "sprintf snprintf fopen fclose fflush fputs fgets fscanf sscanf malloc "
          "calloc realloc free memcpy memset strcmp strcpy strcat strlen strdup "
          "assert exit atoi atof stderr stdout stdin").split()


# ---------------------------------------------------------------------------
# Index of headers

GRIDS = {"quadtree", "octree", "bitree", "multigrid", "multigrid1D",
         "multigrid3D", "cartesian", "cartesian1D", "tree", "layers"}
HEADER_SKIP = {"ast", "test", "examples", "darcsit", "build-env", "figures",
               "notes", "wsServer"}


def _mtime(p):
    try:
        return os.stat(p).st_mtime
    except OSError:
        return None


class Index:
    """Cache of scanned files, shared by all configurations."""

    def __init__(self):
        self.files = {}        # path -> (mtime, FileInfo)
        self.headers = {}      # root -> (dir mtimes, list of (relpath, abspath))
        self.lock = threading.Lock()

    def info(self, path, text=None):
        if text is not None:
            return scan(text, path)
        try:
            mt = os.stat(path).st_mtime
        except OSError:
            return None
        with self.lock:
            c = self.files.get(path)
            if c and c[0] == mt:
                return c[1]
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                fi = scan(f.read(), path)
        except OSError:
            return None
        with self.lock:
            self.files[path] = (mt, fi)
        return fi

    def resolve(self, name, from_dir, cfg):
        dirs = [from_dir] + cfg["idirs"] + ([cfg["root"]] if cfg["root"] else [])
        for d in dirs:
            p = os.path.normpath(os.path.join(d, name))
            if os.path.isfile(p):
                return p
        return None

    def closure(self, path, fi, cfg):
        """Paths of the headers included (transitively) by a file, plus the
        headers implicitly included by qcc."""
        seen, order = {path}, []
        queue = [(os.path.dirname(path), fi.includes)]
        grid_given = any(f.startswith("-grid=") for f in cfg["flags"])
        while queue:
            d, incs = queue.pop(0)
            for delim, name, _ in incs:
                if delim == "<":
                    continue
                if name.startswith("grid/") and os.path.splitext(os.path.basename(name))[0] in GRIDS:
                    grid_given = True
                p = self.resolve(name, d, cfg)
                if p and p not in seen:
                    seen.add(p)
                    order.append(p)
                    sub = self.info(p)
                    if sub:
                        queue.append((os.path.dirname(p), sub.includes))
        implicit = ["common.h"]
        if not grid_given:
            implicit.append("grid/quadtree.h")
        for flag in cfg["flags"]:
            if flag.startswith("-grid="):
                implicit.append("grid/" + flag[6:] + ".h")
        root = cfg["root"]
        if root:
            queue = []
            for name in implicit:
                p = os.path.join(root, name)
                if os.path.isfile(p) and p not in seen:
                    seen.add(p)
                    order.append(p)
                    sub = self.info(p)
                    if sub:
                        queue.append((os.path.dirname(p), sub.includes))
            while queue:
                d, incs = queue.pop(0)
                for delim, name, _ in incs:
                    if delim == "<":
                        continue
                    p = self.resolve(name, d, cfg)
                    if p and p not in seen:
                        seen.add(p)
                        order.append(p)
                        sub = self.info(p)
                        if sub:
                            queue.append((os.path.dirname(p), sub.includes))
        return order

    def header_list(self, cfg, extra_dir=None):
        """Headers for #include completion: the document's directory, the
        include directories, then Basilisk's. Refreshed when a directory
        changes."""
        out = []
        root = cfg["root"]
        if root:
            c = self.headers.get(root)
            if c is None or any(_mtime(d) != m for d, m in c[0].items()):
                mtimes, hs = {}, []
                for d, dirs, files in os.walk(root):
                    rel = os.path.relpath(d, root)
                    top = rel.split(os.sep)[0]
                    dirs[:] = sorted(x for x in dirs if not x.startswith(".")
                                     and not (rel == "." and x in HEADER_SKIP))
                    if top in HEADER_SKIP:
                        continue
                    mtimes[d] = _mtime(d)
                    for f in sorted(files):
                        if f.endswith(".h"):
                            hs.append((os.path.normpath(os.path.join(rel, f)), os.path.join(d, f)))
                c = self.headers[root] = (mtimes, hs)
            out = list(c[1])
        for d in reversed([extra_dir] + cfg["idirs"]):
            if d and os.path.isdir(d) and d != root:
                out[:0] = [(f, os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".h")]
        return out

    def title(self, path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                head = f.read(4096)
        except OSError:
            return ""
        m = re.search(r"/\*\*?(.*?)(\*/|\Z)", head, re.S)
        if not m:
            return ""
        c = m.group(1)
        t = re.search(r"^\s*#+\s*(.+)$", c, re.M)
        return t.group(1).strip() if t else squash(c, 80)


# ---------------------------------------------------------------------------
# Diagnostics (via qcc)

DIAG_RE = re.compile(r"^(?P<file>[^:\n]+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
                     r"(?P<sev>fatal error|error|warning|note)\s*:\s*(?P<msg>.*)$")
CTX_RE = re.compile(r"^(?P<file>[^:\n]+?):\s*In (?:member )?function\s+"
                    r"[‘'`\"](?P<fn>[^’'`\"]+)[’'`\"]")
QUOTED_ID = re.compile(r"[‘'`\"](" + ID + r")[’'`\"]")
SEV = {"error": 1, "fatal error": 1, "warning": 2, "note": 3}
GENERIC_RE = re.compile(r"^(?:qcc|cc|gcc|cc1|ld|collect2): (fatal error|error|warning): (.*)$")


# Test hooks: QCC_RECORD(files, main, out, returncode, tmp) is called after
# each qcc run; QCC_REPLAY(files, main, tmp) -> (out, returncode) replaces
# running qcc (see tests/fixtures/diagnostics).
QCC_RECORD = None
QCC_REPLAY = None


def resolve_reported(f, tmp, files, idirs):
    """Maps a file name reported by qcc/gcc to the real file."""
    n = os.path.normpath(os.path.join(tmp, f) if not os.path.isabs(f) else f)
    rel = os.path.relpath(n, tmp)
    if rel in files:
        return files[rel][1] or f
    if not os.path.isabs(f):
        for d in idirs:
            p = os.path.join(d, f)
            if os.path.isfile(p):
                return os.path.realpath(p)
    return os.path.realpath(f) if os.path.isabs(f) else f


def parse_qcc_output(out, returncode, resolve, target):
    """qcc/gcc output -> list of [file, line, col, sev, msg, ctx].
    `resolve` maps reported file names to real files; errors without a
    location (e.g. "qcc: error: cannot parse input") go to `target`."""
    raw, ctx, last = [], None, None
    for l in out.splitlines():
        m = CTX_RE.match(l)
        if m:
            ctx = m.group("fn")
            last = None
            continue
        m = DIAG_RE.match(l)
        if m:
            last = [resolve(m.group("file")), int(m.group("line")),
                    int(m.group("col")) if m.group("col") else None,
                    m.group("sev"), m.group("msg"), ctx]
            raw.append(last)
            continue
        m = GENERIC_RE.match(l)
        if m:
            last = [target, 1, None, m.group(1), m.group(2), None]
            raw.append(last)
            continue
        if (l.startswith("In file included") or re.match(r"^\s+from ", l)
                or re.match(r"^[^:]+: At top level:", l)
                or re.match(r"^\s*\d*\s*\|", l) or l.startswith("compilation terminated")):
            last = None
            continue
        if last is not None and l.strip():
            last[4] += "\n" + l   # continuation (e.g. qcc parse error snippets)
    if returncode and not any(r[3] in ("error", "fatal error") for r in raw):
        # failed, but nothing we recognised: never report a clean file
        tail = [l for l in out.splitlines() if l.strip()][-3:]
        raw.append([target, 1, None, "error",
                    f"qcc failed (exit status {returncode})" +
                    (": " + " / ".join(tail) if tail else ""), None])
    return raw


def run_qcc(cfg, files, main, idir, procs=None, key=None):
    """Runs `qcc -fsyntax-only main` in a temporary directory holding
    `files` ({name: (text, real path or None)}), with -I`idir`.

    Returns (raw, None) where raw is a list of diagnostics
    [real path or reported name, line, col, sev, msg, ctx], or
    (None, error message) / (None, None) if superseded."""
    qcc = cfg["qccExe"]
    if not qcc or not cfg["root"]:
        return None, " ".join(cfg["errors"]) or "qcc not found"
    flags = list(cfg["flags"])
    tmp = tempfile.mkdtemp(prefix="basilisk-lsp-")
    idirs = [idir] + cfg["idirs"] + [cfg["root"]]
    try:
        for name, (text, _) in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                f.write(text)
        if QCC_REPLAY:
            out, returncode = QCC_REPLAY(files, main, tmp)
        else:
            env = dict(os.environ)
            env["BASILISK"] = cfg["root"]
            env["PATH"] = os.path.dirname(qcc) + os.pathsep + env.get("PATH", "")
            cmd = [qcc] + flags + ["-fsyntax-only", "-I" + idir, main]
            p = subprocess.Popen(cmd, cwd=tmp, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            if procs is not None:
                procs[key] = p
            try:
                out, _ = p.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                p.kill()
                out, _ = p.communicate()
            out = out.decode("utf-8", errors="replace")
            returncode = p.returncode
            if returncode is not None and returncode < 0:
                return None, None   # killed (superseded)
            if QCC_RECORD:
                QCC_RECORD(files, main, out, returncode, tmp)
        target = files[main][1] or next((r for _, r in files.values() if r), main)
        raw = parse_qcc_output(out, returncode,
                               lambda f: resolve_reported(f, tmp, files, idirs), target)
        return raw, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


WRAPPER = "_basilisk_lsp_check.c"
MAX_FOREIGN = 10   # max. diagnostics reported in other files, per check


def find_context(server, path, docs, cfg):
    """A .c file including header `path`: an open document first, then a
    file in the same directory. Returns (c path, c text) or None."""
    target = os.path.realpath(path)
    cands = []
    for uri, d in list(docs.items()):
        p = uri_to_path(uri)
        if p.endswith(".c"):
            cands.append((p, d["text"]))
    hd = os.path.dirname(path)
    try:
        local = sorted((os.path.join(hd, f) for f in os.listdir(hd) if f.endswith(".c")),
                       key=lambda f: -os.path.getmtime(f))[:100]
    except OSError:
        local = []
    open_paths = {p for p, _ in cands}
    for p in local:
        if p not in open_paths:
            cands.append((p, None))
    for p, text in cands:
        try:
            fi = scan(text, p) if text is not None else server.index.info(p)
        except OSError:
            continue
        if fi and target in {os.path.realpath(f) for f in server.index.closure(p, fi, cfg)}:
            if text is None:
                with open(p, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            return p, text
    return None


def check(server, path, text, docs=None, procs=None, key=None):
    """Diagnostics for `path` (with contents `text`).
    Returns (diagnostics, error) — diagnostics None means 'keep the old ones'."""
    path = os.path.abspath(path)
    cfg = server.config(path)
    d, base = os.path.dirname(path), os.path.basename(path)
    if not path.endswith(".h"):
        raw, err = run_qcc(cfg, {base: (text, os.path.realpath(path))}, base, d, procs, key)
        return (None, err) if raw is None else (make_diagnostics(cfg, path, text, raw), None)

    # Headers are not compiled on their own by qcc: check them through
    # a .c file which includes them.
    ctx = find_context(server, path, docs or {}, cfg)
    if ctx:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                saved = f.read() == text
        except OSError:
            saved = False
        if not saved:
            return None, None   # checked on save, in context
        cpath, ctext = ctx
        cbase = os.path.basename(cpath)
        raw, err = run_qcc(server.config(cpath), {cbase: (ctext, os.path.realpath(cpath))}, cbase,
                           os.path.dirname(cpath), procs, key)
        if raw is None:
            return None, err
        target = os.path.realpath(path)
        raw = [r for r in raw if r[0] == target]
        return make_diagnostics(cfg, path, text, raw, foreign=False), None

    files = {base: (text, os.path.realpath(path)),
             WRAPPER: (f'#include "{base}"\n', None)}
    raw, err = run_qcc(cfg, files, WRAPPER, d, procs, key)
    if raw is None:
        return None, err
    diags = make_diagnostics(cfg, path, text, raw, foreign=False)
    errors = [x for x in diags if x["severity"] == 1 and "parse error" not in x["message"]]
    if errors:
        # most likely a header which needs other headers included before it
        diags = [x for x in diags if "parse error" in x["message"]]
        diags.append({
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
            "severity": 3, "source": "qcc",
            "message": (f"This header does not compile on its own ({len(errors)} errors, e.g. "
                        f"line {errors[0]['range']['start']['line'] + 1}: {errors[0]['message'][:120]}). "
                        "It probably needs other headers included before it: open (or create, in "
                        "this directory) a .c file which includes it to check it in context.")})
    return diags, None


def idx_to_u16(s, i):
    """Python string index -> LSP (UTF-16) column."""
    return len(s[:i].encode("utf-16-le")) // 2


def byte_to_idx(s, b):
    """UTF-8 byte offset (as reported by gcc) -> Python string index."""
    return len(s.encode("utf-8")[:b].decode("utf-8", errors="ignore"))


def make_diagnostics(cfg, path, text, raw, foreign=True):
    """Maps raw qcc/gcc diagnostics onto the document. Diagnostics reported
    in other files are attached to the closest location in the document,
    unless `foreign` is False."""
    target = os.path.realpath(path)
    code, _, _ = blank_comments(text)
    clines = code.split("\n")
    olines = text.split("\n")
    local = scan(text, path).symbols
    parse_error = any("parse error" in r[4] for r in raw if r[0] == target)
    diags, seen = [], set()
    nforeign = 0

    def u16(l, c):
        return idx_to_u16(olines[l], c) if 0 <= l < len(olines) else c

    def rng(l0, c0, l1, c1):
        return {"start": {"line": l0, "character": u16(l0, c0)},
                "end": {"line": l1, "character": u16(l1, c1)}}

    def line_range(l):
        l = max(0, min(l, len(olines) - 1))
        s = olines[l]
        return rng(l, len(s) - len(s.lstrip()), l, len(s))

    for f, line, col, sev, msg, ctx in raw:
        ours = f == target
        nl = msg.count("\n")
        text_msg = squash(msg, 400)
        if ours:
            l = line - 1
            if col:
                s = olines[l] if 0 <= l < len(olines) else ""
                c = byte_to_idx(s, col - 1)
                m = re.match(r"\w+", s[c:])
                r = rng(l, c, l, c + (len(m.group()) if m else 1))
            elif nl and "parse error" in msg:
                r = line_range(l - nl)
                r["end"] = line_range(l)["end"]
            else:
                r = line_range(l)
        else:
            # reported in a header (code expanded from a foreach, macro...)
            if not foreign or parse_error or sev == "note":
                continue
            nforeign += 1
            if nforeign > MAX_FOREIGN:
                continue
            rel = f
            if cfg["root"] and f.startswith(cfg["root"] + os.sep):
                rel = os.path.relpath(f, cfg["root"])
            text_msg += f"  [reported in {rel}:{line}]"
            anchor = None
            if ctx:
                b = re.sub(r"_\d+$", "", ctx)
                for s in local:
                    if s.name in (ctx, b) and s.kind in ("event", "function", "macro"):
                        anchor = s.line
                        break
            r = None
            for ident in QUOTED_ID.findall(msg):
                pat = re.compile(r"\b" + re.escape(ident) + r"\b")
                for k in range(anchor or 0, len(clines)):
                    m = pat.search(clines[k])
                    if m:
                        r = rng(k, m.start(), k, m.end())
                        break
                if r:
                    break
            if r is None:
                r = line_range(anchor if anchor is not None else 0)
        key = (r["start"]["line"], text_msg)
        if key in seen:
            continue
        seen.add(key)
        diags.append({"range": r, "severity": SEV.get(sev, 1),
                      "source": "qcc", "message": text_msg})
    if nforeign > MAX_FOREIGN:
        diags.append({"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                      "severity": 2, "source": "qcc",
                      "message": f"… and {nforeign - MAX_FOREIGN} more diagnostics reported in other files"})
    return diags


# ---------------------------------------------------------------------------
# LSP server

def uri_to_path(uri):
    p = urllib.parse.urlparse(uri)
    return urllib.parse.unquote(p.path) if p.scheme == "file" else uri


def path_to_uri(path):
    return "file://" + urllib.parse.quote(os.path.abspath(path))


def u16_to_idx(s, col):
    n = 0
    for i, ch in enumerate(s):
        if n >= col:
            return i
        n += 2 if ord(ch) > 0xFFFF else 1
    return len(s)


CIK = {"function": 3, "macro": 3, "define": 21, "event": 23, "field": 6,
       "variable": 6, "type": 22, "keyword": 14, "snippet": 15, "file": 17,
       "text": 1, "module": 9}
SK = {"function": 12, "macro": 12, "define": 14, "event": 24, "field": 13,
      "variable": 13, "type": 23}


class Server:
    def __init__(self, extra_flags=None):
        self.settings = {}           # editor settings (lowest precedence after defaults)
        self.extra_flags = list(extra_flags or [])
        self._cfg_cache = {}
        self.docs = {}
        self.out_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.timers = {}
        self.procs = {}
        self.snippets = False
        self.resolve_store = {}
        self.index = Index()
        self.running = True
        self.warned = set()

    # -- configuration
    def set_config(self, opts):
        """Editor settings: {"qccFlags": [...], ...}, possibly nested in a
        "basilisk" section (VS Code, where basiliskPath is called "path")."""
        if not isinstance(opts, dict):
            return
        if isinstance(opts.get("basilisk"), dict):
            opts = opts["basilisk"]
        if "path" in opts and "basiliskPath" not in opts:
            opts = dict(opts, basiliskPath=opts["path"])
        self.settings = {k: opts[k] for k in DEFAULTS if opts.get(k) is not None}
        self._cfg_cache = {}

    def config(self, path):
        """Effective configuration for `path`, cached briefly per directory
        (a completion request asks for it thousands of times)."""
        d = os.path.dirname(os.path.abspath(path))
        c = self._cfg_cache.get(d)
        now = time.monotonic()
        if c and now - c[0] < 2.0:
            return c[1]
        cfg = resolve_config(self.settings, path)
        if self.extra_flags:
            cfg["flags"] = cfg["flags"] + self.extra_flags
            cfg["idirs"] = cfg["idirs"] + [f[2:] for f in self.extra_flags
                                           if f.startswith("-I") and len(f) > 2]
        self._cfg_cache[d] = (now, cfg)
        return cfg

    def warn(self, msg):
        if msg not in self.warned:
            self.warned.add(msg)
            log(msg)
            self.notify("window/showMessage", {"type": 2, "message": "basilisk-lsp: " + msg})

    # -- transport
    def send(self, msg):
        msg["jsonrpc"] = "2.0"
        body = json.dumps(msg).encode("utf-8")
        with self.out_lock:
            sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
            sys.stdout.buffer.flush()

    def notify(self, method, params):
        self.send({"method": method, "params": params})

    def read(self):
        headers = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            line = line.decode("ascii", errors="replace").strip()
            if not line:
                break
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        n = int(headers.get("content-length", 0))
        body = sys.stdin.buffer.read(n)
        return json.loads(body.decode("utf-8"))

    def serve(self):
        while self.running:
            msg = self.read()
            if msg is None:
                break
            method, mid = msg.get("method"), msg.get("id")
            try:
                handler = getattr(self, "on_" + (method or "").replace("/", "_").replace("$", "S"), None)
                if handler is None:
                    if mid is not None and method:
                        self.send({"id": mid, "error": {"code": -32601,
                                   "message": "method not found: " + method}})
                    continue
                result = handler(msg.get("params") or {})
                if mid is not None:
                    self.send({"id": mid, "result": result})
            except Exception as e:  # keep serving
                import traceback
                log(traceback.format_exc())
                if mid is not None:
                    self.send({"id": mid, "error": {"code": -32603, "message": str(e)}})

    # -- lifecycle
    def on_initialize(self, p):
        self.set_config(p.get("initializationOptions") or {})
        caps = p.get("capabilities") or {}
        self.snippets = bool(caps.get("textDocument", {}).get("completion", {})
                             .get("completionItem", {}).get("snippetSupport"))
        log("version", VERSION, "settings", json.dumps(self.settings))
        return {
            "capabilities": {
                "textDocumentSync": {"openClose": True, "change": 1,
                                     "save": {"includeText": False}},
                "completionProvider": {"triggerCharacters": ['"', "/", ".", "<"],
                                       "resolveProvider": True},
                "hoverProvider": True,
                "definitionProvider": True,
                "documentSymbolProvider": True,
            },
            "serverInfo": {"name": "basilisk-lsp", "version": VERSION},
        }

    def on_initialized(self, p):
        pass

    def on_shutdown(self, p):
        return None

    def on_exit(self, p):
        self.running = False

    def on_workspace_didChangeConfiguration(self, p):
        self.set_config(p.get("settings") or {})

    # -- documents
    def on_textDocument_didOpen(self, p):
        d = p["textDocument"]
        self.docs[d["uri"]] = {"text": d["text"], "version": d.get("version", 0)}
        for err in self.config(uri_to_path(d["uri"]))["errors"]:
            self.warn(err)
        self.schedule(d["uri"], 0)

    def on_textDocument_didChange(self, p):
        uri = p["textDocument"]["uri"]
        doc = self.docs.setdefault(uri, {"text": "", "version": 0})
        for ch in p.get("contentChanges", []):
            if "range" not in ch:
                doc["text"] = ch["text"]
            else:
                doc["text"] = apply_change(doc["text"], ch)
        doc["version"] = p["textDocument"].get("version", doc["version"] + 1)
        cfg = self.config(uri_to_path(uri))
        if cfg.get("diagnostics") == "onChange":
            self.schedule(uri, float(cfg.get("debounce") or 1.0))

    def on_textDocument_didSave(self, p):
        self.schedule(p["textDocument"]["uri"], 0)

    def on_textDocument_didClose(self, p):
        uri = p["textDocument"]["uri"]
        self.docs.pop(uri, None)
        with self.state_lock:
            t = self.timers.pop(uri, None)
            if t:
                t.cancel()
        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})

    def schedule(self, uri, delay):
        if self.config(uri_to_path(uri)).get("diagnostics") == "off":
            return
        with self.state_lock:
            t = self.timers.pop(uri, None)
            if t:
                t.cancel()
            t = threading.Timer(delay, self.diagnose, (uri,))
            t.daemon = True
            self.timers[uri] = t
            t.start()

    def diagnose(self, uri):
        doc = self.docs.get(uri)
        if not doc:
            return
        version, text = doc["version"], doc["text"]
        with self.state_lock:
            old = self.procs.get(uri)
            if old and old.poll() is None:
                old.kill()
        path = uri_to_path(uri)
        diags, err = check(self, path, text, self.docs, self.procs, uri)
        if diags is None:
            if err:
                self.warn(err)
            return
        cur = self.docs.get(uri)
        if not cur or cur["version"] != version:
            return
        self.notify("textDocument/publishDiagnostics",
                    {"uri": uri, "version": version, "diagnostics": diags})

    # -- symbol lookup
    def context(self, uri):
        doc = self.docs.get(uri) or {"text": ""}
        path = uri_to_path(uri)
        cfg = self.config(path)
        cache = doc.get("_ctx")
        if (cache and cache[0] == (doc.get("version"), cfg["key"])
                and all(_mtime(f) == m for f, m in cache[2])):
            return cache[1]
        fi = scan(doc["text"], path)
        files = self.index.closure(path, fi, cfg)
        table = {}
        for s in fi.symbols:
            table.setdefault(s.name, []).append(s)
        for f in files:
            info = self.index.info(f)
            if not info:
                continue
            for s in info.symbols:
                lst = table.setdefault(s.name, [])
                if s.kind == "event" or not lst or all(x.path != s.path for x in lst):
                    lst.append(s)
        ctx = (fi, files, table)
        doc["_ctx"] = ((doc.get("version"), cfg["key"]), ctx, [(f, _mtime(f)) for f in files])
        return ctx

    def word_at(self, uri, pos):
        text = (self.docs.get(uri) or {}).get("text", "")
        lines = text.split("\n")
        if pos["line"] >= len(lines):
            return "", "", 0
        s = lines[pos["line"]]
        i = u16_to_idx(s, pos["character"])
        a = i
        while a > 0 and (s[a - 1].isalnum() or s[a - 1] == "_"):
            a -= 1
        b = i
        while b < len(s) and (s[b].isalnum() or s[b] == "_"):
            b += 1
        return s[a:b], s, i

    def include_at(self, uri, pos):
        _, line, i = self.word_at(uri, pos)
        m = RE_INCLUDE.match(line)
        if not m or m.group(1) == "<":
            return None
        path = uri_to_path(uri)
        return self.index.resolve(m.group(2).strip(), os.path.dirname(path), self.config(path))

    def relname(self, path, uri=None):
        root = self.config(uri_to_path(uri))["root"] if uri else None
        if root and path.startswith(root + os.sep):
            return os.path.relpath(path, root)
        if uri:
            d = os.path.dirname(uri_to_path(uri))
            if path.startswith(d + os.sep):
                return os.path.relpath(path, d)
        return path

    def markdown(self, name, syms, uri):
        parts = []
        b = BUILTINS.get(name)
        if b and (not syms or b[0] in ("keyword", "type")):
            parts.append("```c\n" + b[1] + "\n```\n" + b[2])
        elif syms:
            s = syms[0]
            parts.append("```c\n" + s.sig + "\n```")
            if s.doc:
                parts.append(s.doc)
        if syms:
            locs = [f"`{self.relname(s.path, uri)}:{s.line + 1}`" for s in syms[:8]]
            more = f" (+{len(syms) - 8})" if len(syms) > 8 else ""
            parts.append("*Defined in* " + ", ".join(locs) + more)
        elif b and not parts:
            parts.append("```c\n" + b[1] + "\n```\n" + b[2])
        return "\n\n".join(parts)

    def sym_range(self, s, uri):
        """LSP range of a symbol's name (UTF-16 columns)."""
        if s.path == uri_to_path(uri) and uri in self.docs:
            lines = self.docs[uri]["text"].split("\n")
        else:
            try:
                with open(s.path, encoding="utf-8", errors="replace") as f:
                    lines = f.read().split("\n")
            except OSError:
                lines = []
        line = lines[s.line] if s.line < len(lines) else ""
        return {"start": {"line": s.line, "character": idx_to_u16(line, s.col)},
                "end": {"line": s.line, "character": idx_to_u16(line, s.col + len(s.name))}}

    # -- requests
    def on_textDocument_hover(self, p):
        uri, pos = p["textDocument"]["uri"], p["position"]
        inc = self.include_at(uri, pos)
        if inc:
            fi = self.index.info(inc)
            t = (fi.title if fi else "") or ""
            return {"contents": {"kind": "markdown",
                    "value": (f"**{t}**\n\n" if t else "") + f"`{inc}`"}}
        word, _, _ = self.word_at(uri, pos)
        if not word:
            return None
        _, _, table = self.context(uri)
        syms = table.get(word, [])
        if not syms and word not in BUILTINS:
            return None
        return {"contents": {"kind": "markdown", "value": self.markdown(word, syms, uri)}}

    def on_textDocument_definition(self, p):
        uri, pos = p["textDocument"]["uri"], p["position"]
        inc = self.include_at(uri, pos)
        if inc:
            return [{"uri": path_to_uri(inc), "range": {
                "start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}}]
        word, _, _ = self.word_at(uri, pos)
        if not word:
            return None
        _, _, table = self.context(uri)
        out = []
        for s in table.get(word, [])[:30]:
            u = uri if s.path == uri_to_path(uri) else path_to_uri(s.path)
            out.append({"uri": u, "range": self.sym_range(s, uri)})
        return out or None

    def on_textDocument_documentSymbol(self, p):
        uri = p["textDocument"]["uri"]
        fi, _, _ = self.context(uri)
        out = []
        for s in fi.symbols:
            name = s.name if s.kind != "event" else "event " + s.name
            out.append({"name": name, "kind": SK.get(s.kind, 13), "detail": s.sig,
                        "location": {"uri": uri, "range": self.sym_range(s, uri)}})
        return out

    def on_textDocument_completion(self, p):
        uri, pos = p["textDocument"]["uri"], p["position"]
        text = (self.docs.get(uri) or {}).get("text", "")
        lines = text.split("\n")
        line = lines[pos["line"]] if pos["line"] < len(lines) else ""
        i = u16_to_idx(line, pos["character"])
        before = line[:i]
        self.resolve_store = {}

        # #include "...
        m = re.match(r'^\s*#\s*include\s*"([^"]*)$', before)
        if m:
            typed = m.group(1)
            start = i - len(typed)
            items = []
            d = os.path.dirname(uri_to_path(uri))
            for rel, absp in self.index.header_list(self.config(uri_to_path(uri)), d):
                k = str(len(self.resolve_store))
                self.resolve_store[k] = ("header", absp)
                items.append({"label": rel, "kind": CIK["file"], "data": {"k": k},
                              "filterText": rel, "sortText": ("0" if "/" not in rel else "1") + rel,
                              "textEdit": {"range": {
                                  "start": {"line": pos["line"], "character": start},
                                  "end": {"line": pos["line"], "character": pos["character"]}},
                                  "newText": rel}})
            return {"isIncomplete": False, "items": items}

        fi, files, table = self.context(uri)

        # member access: u.x, T.x.y, p.x ...
        m = re.search(r"(" + ID + r")\s*(\.\s*[xyz]\s*)*\.\s*(\w*)$", before)
        if m and not re.search(r"\d\.\w*$", before):
            base = m.group(1)
            syms = table.get(base, [])
            ftype = syms[0].ftype or syms[0].sig if syms else ""
            if not syms or re.search(r"vector|tensor|coord", ftype or ""):
                return {"isIncomplete": False, "items": [
                    {"label": c, "kind": CIK["field"], "detail": base + "." + c}
                    for c in ("x", "y", "z")]}
            return {"isIncomplete": False, "items": []}

        items, seen = [], set()

        def item(label, kind, detail, sort, key=None, snippet=None):
            if label in seen:
                return
            seen.add(label)
            it = {"label": label, "kind": CIK.get(kind, 1), "sortText": sort + label}
            if detail:
                it["detail"] = detail
            if key is not None:
                it["data"] = {"k": key}
            if snippet and self.snippets:
                it["insertText"] = snippet
                it["insertTextFormat"] = 2
            items.append(it)

        path = uri_to_path(uri)
        # local symbols first
        for s in fi.symbols:
            k = str(len(self.resolve_store))
            self.resolve_store[k] = ("sym", s.name, uri)
            item(s.name, s.kind, s.sig, "0", k)
        for name, (kind, sig, _) in BUILTINS.items():
            k = str(len(self.resolve_store))
            self.resolve_store[k] = ("sym", name, uri)
            item(name, kind, sig, "1", k, SNIPPETS.get(name))
        for name in SNIPPETS:
            item(name, "snippet", "", "1", None, SNIPPETS[name])
        for name, syms in table.items():
            s = syms[0]
            if s.path == path:
                continue
            k = str(len(self.resolve_store))
            self.resolve_store[k] = ("sym", name, uri)
            item(name, s.kind, s.sig + "  — " + self.relname(s.path, uri), "2", k)
        for w in C_KEYWORDS:
            item(w, "keyword", "", "3")
        for w in STDLIB:
            item(w, "function", "C library", "3")
        for w in set(re.findall(r"\b[A-Za-z_]\w{2,}\b", blank_comments(text)[0])):
            item(w, "text", "", "4")
        return {"isIncomplete": False, "items": items}

    def on_completionItem_resolve(self, item):
        k = (item.get("data") or {}).get("k")
        entry = self.resolve_store.get(k)
        if not entry:
            return item
        if entry[0] == "header":
            fi = self.index.info(entry[1])
            t = fi.title if fi else ""
            item["documentation"] = {"kind": "markdown",
                                     "value": (f"**{t}**\n\n" if t else "") + entry[1]}
            return item
        _, name, uri = entry
        syms = self.context(uri)[2].get(name, []) if uri in self.docs else []
        md = self.markdown(name, syms, uri)
        if md:
            item["documentation"] = {"kind": "markdown", "value": md}
        return item


def apply_change(text, ch):
    lines = text.split("\n")
    r = ch["range"]

    def off(pos):
        l = pos["line"]
        o = sum(len(x) + 1 for x in lines[:l])
        return o + (u16_to_idx(lines[l], pos["character"]) if l < len(lines) else 0)

    a, b = off(r["start"]), off(r["end"])
    return text[:a] + ch["text"] + text[b:]


# ---------------------------------------------------------------------------
# Command line

def lint(path, flags):
    server = Server(extra_flags=flags)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    diags, err = check(server, path, text)
    if diags is None:
        print(f"{path}:1:1: error: {err}")
        return 2
    names = {1: "error", 2: "warning", 3: "note"}
    lines = text.split("\n")
    for d in diags:
        s = d["range"]["start"]
        line = lines[s["line"]] if s["line"] < len(lines) else ""
        col = u16_to_idx(line, s["character"]) + 1
        msg = d["message"].replace("\n", " ")
        print(f"{path}:{s['line'] + 1}:{col}: {names[d['severity']]}: {msg}")
    return 1 if any(d["severity"] == 1 for d in diags) else 0


def main(argv):
    if "--version" in argv:
        print("basilisk-lsp", VERSION)
        return 0
    if "--config" in argv:
        rest = argv[argv.index("--config") + 1:]
        cfg = Server().config(rest[0] if rest else os.path.join(os.getcwd(), "x.c"))
        print(json.dumps({k: v for k, v in cfg.items() if k != "key"}, indent=2))
        return 1 if cfg["errors"] else 0
    if "--lint" in argv:
        i = argv.index("--lint")
        rest = argv[i + 1:]
        if not rest:
            print("usage: basilisk-lsp --lint FILE [qcc flags]", file=sys.stderr)
            return 2
        return lint(rest[0], rest[1:])
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    Server().serve()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
