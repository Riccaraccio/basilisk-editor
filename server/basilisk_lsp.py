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
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse

VERSION = "0.1.0"

DEFAULTS = {
    "qcc": "qcc",              # qcc executable
    "qccFlags": ["-Wall"],     # extra flags for diagnostics (e.g. -grid=octree)
    "diagnostics": "onChange", # "onChange" | "onSave" | "off"
    "debounce": 1.0,           # seconds, for onChange
    "basilisk": None,          # path to $BASILISK (the src/ directory)
}


def log(*args):
    print("[basilisk-lsp]", *args, file=sys.stderr, flush=True)


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

def B(kind, sig, doc):
    return (kind, sig, doc)


BUILTINS = {
    "foreach": B("keyword", "foreach (reduction(op:var) ...) statement",
        "Loops over all the leaf cells of the grid (in parallel with OpenMP/MPI).\n\n"
        "Inside the loop: `x`, `y`, `z` are the coordinates of the cell centre, "
        "`Delta` is the cell size, `point` the current `Point`, and fields are "
        "accessed through stencils: `s[]`, `s[1]`, `s[-1,0]`, `s[0,1]`...\n\n"
        "Global accumulations must be declared with `reduction(+:sum)` "
        "(also `min`, `max`)."),
    "foreach_face": B("keyword", "foreach_face (x|y|z, reduction(...)) statement",
        "Loops over the faces of the leaf cells. The body is written for the "
        "*x* direction and automatically rotated for the other directions "
        "(as with `foreach_dimension()`); `foreach_face(x)` restricts the loop "
        "to the *x* faces. Use it to update `face vector` fields: `uf.x[]` is "
        "the value on the face between `[-1]` and `[]`."),
    "foreach_vertex": B("keyword", "foreach_vertex () statement",
        "Loops over the vertices of the leaf cells (for `vertex` fields)."),
    "foreach_dimension": B("keyword", "foreach_dimension () statement",
        "Repeats the following statement (or function definition) for each "
        "dimension, rotating `x`→`y`→`z` in component names (`.x`, `_x`) and "
        "stencil indices."),
    "foreach_level": B("keyword", "foreach_level (int l) statement",
        "Loops over all the cells at level `l` of the tree."),
    "foreach_level_or_leaf": B("keyword", "foreach_level_or_leaf (int l) statement",
        "Loops over the cells at level `l` and the leaf cells coarser than `l`."),
    "foreach_coarse_level": B("keyword", "foreach_coarse_level (int l) statement",
        "Loops over the non-leaf cells at level `l`."),
    "foreach_leaf": B("keyword", "foreach_leaf () statement",
        "Loops over the leaf cells (equivalent to `foreach()`)."),
    "foreach_cell": B("keyword", "foreach_cell () statement",
        "Depth-first traversal of the whole tree, starting from the root. Use "
        "`continue` to skip the children of the current cell and "
        "`is_leaf(cell)` to detect leaves."),
    "foreach_child": B("keyword", "foreach_child () statement",
        "Loops over the children of the current cell."),
    "foreach_neighbor": B("keyword", "foreach_neighbor (int n = 2) statement",
        "Loops over the neighbours of the current cell, within a stencil of "
        "half-width `n`."),
    "foreach_boundary": B("keyword", "foreach_boundary (int b) statement",
        "Loops over the cells adjacent to boundary `b` (e.g. `left`)."),
    "foreach_point": B("keyword", "foreach_point (double x, double y, double z) statement",
        "Executes the statement on the leaf cell containing the point (x, y, z)."),
    "foreach_fine_to_coarse": B("keyword", "foreach_fine_to_coarse () statement",
        "Loops over the non-leaf cells, from the finest to the coarsest level."),
    "foreach_block": B("keyword", "foreach_block () statement",
        "Loops over the blocks/layers of block data (multilayer solver)."),
    "foreach_layer": B("keyword", "foreach_layer () statement",
        "Loops over the layers (multilayer solver). Inside, `point.l` is the "
        "layer index."),
    "event": B("keyword", "event name (condition; ...) { ... }",
        "Defines an event, executed by `run()` when its conditions are met.\n\n"
        "Conditions: `i = 0`, `i++`, `i += 10`, `t = 0`, `t += 0.1`, "
        "`t <= 10`, `t = end`, `first`, `last`, `t = {0, 1, 2}`... "
        "Events with the same name as an existing event (e.g. `init`, "
        "`logfile`, `adapt`) are added to it; returning 1 stops the run."),
    "reduction": B("keyword", "reduction (op : var)",
        "Declares a parallel reduction for a `foreach` loop. `op` is `+`, "
        "`min` or `max`; `var` is a variable or an array `var[:n]`."),
    "scalar": B("type", "scalar s[];",
        "A scalar field. Global or local declarations `scalar s[];` allocate "
        "the field (local fields are freed automatically at the end of the "
        "scope); `scalar s = new scalar;` allocates dynamically. "
        "Values are accessed inside `foreach` loops as `s[]`, `s[1,0]`..."),
    "vector": B("type", "vector u[];",
        "A vector field, with components `u.x`, `u.y` (and `u.z`)."),
    "tensor": B("type", "tensor T[];",
        "A tensor field, with components `T.x.x`, `T.x.y`, ..."),
    "face": B("keyword", "face vector uf[];",
        "Qualifier: a `face vector` is staggered on cell faces "
        "(`uf.x[]` lives on the face between `[-1]` and `[]`)."),
    "vertex": B("keyword", "vertex scalar s[];",
        "Qualifier: a `vertex scalar` is defined on cell vertices."),
    "symmetric": B("keyword", "symmetric tensor T[];",
        "Qualifier: a symmetric tensor (`T.x.y` and `T.y.x` share storage)."),
    "new": B("keyword", "new scalar | new vector | new face vector ...",
        "Dynamically allocates a new field; free it with `delete ({s});`."),
    "delete": B("function", "void delete (scalar * list)",
        "Frees the fields in `list`."),
    "trace": B("keyword", "trace", "Marks the following function for profiling (`-DTRACE`)."),
    "macro": B("keyword", "macro [type] name (args) { ... }",
        "Basilisk macro: a function-like definition inlined by qcc, which "
        "can take a code block as its last argument."),
    "Delta": B("variable", "double Delta",
        "Size of the current cell (inside `foreach`-type loops)."),
    "x": B("variable", "double x", "*x*-coordinate of the current cell (or face) centre."),
    "y": B("variable", "double y", "*y*-coordinate of the current cell (or face) centre."),
    "z": B("variable", "double z", "*z*-coordinate of the current cell (or face) centre."),
    "t": B("variable", "double t", "Physical time."),
    "dt": B("variable", "double dt", "Current timestep."),
    "i": B("variable", "int i", "Iteration (timestep) counter."),
    "point": B("variable", "Point point", "The current cell, inside `foreach`-type loops."),
    "level": B("variable", "int level", "Level of the current cell (inside loops)."),
    "dimension": B("define", "dimension", "Number of space dimensions (1, 2 or 3)."),
    "val": B("macro", "val (s, i, j, k)", "Explicit stencil access, equivalent to `s[i,j,k]`."),
    "fine": B("macro", "fine (s, i, j, k)", "Value of field `s` in child cell (i, j, k)."),
    "coarse": B("macro", "coarse (s, i, j, k)", "Value of field `s` in the parent cell."),
    "neighbor": B("macro", "neighbor (i, j, k)", "The neighbouring `Point` at offset (i, j, k)."),
    "left": B("variable", "left", "Left boundary (e.g. `u.n[left] = dirichlet(0);`)."),
    "right": B("variable", "right", "Right boundary."),
    "top": B("variable", "top", "Top boundary."),
    "bottom": B("variable", "bottom", "Bottom boundary."),
    "front": B("variable", "front", "Front boundary (3D)."),
    "back": B("variable", "back", "Back boundary (3D)."),
    "in": B("keyword", "for (scalar s in list)", "Iterates over the fields of a list."),
    "first": B("keyword", "first", "Event condition: first."),
    "last": B("keyword", "last", "Event condition: last (executed after all other events of the same name)."),
    "end": B("keyword", "t = end", "Event condition: the end of the run."),
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


class Index:
    def __init__(self, server):
        self.server = server
        self.files = {}        # path -> (mtime, FileInfo)
        self.headers = None    # cached list of (relpath, abspath)
        self.lock = threading.Lock()

    @property
    def root(self):
        return self.server.basilisk

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

    def include_dirs(self):
        dirs = []
        for f in self.server.cfg.get("qccFlags") or []:
            if f.startswith("-I") and len(f) > 2:
                dirs.append(f[2:])
        if self.root:
            dirs.append(self.root)
        return dirs

    def resolve(self, name, from_dir):
        for d in [from_dir] + self.include_dirs():
            p = os.path.normpath(os.path.join(d, name))
            if os.path.isfile(p):
                return p
        return None

    def closure(self, path, fi):
        """Paths of the headers included (transitively) by a file, plus the
        headers implicitly included by qcc."""
        seen, order = {path}, []
        queue = [(os.path.dirname(path), fi.includes)]
        grid_given = any(f.startswith("-grid=") for f in self.server.cfg.get("qccFlags") or [])
        while queue:
            d, incs = queue.pop(0)
            for delim, name, _ in incs:
                if delim == "<":
                    continue
                if name.startswith("grid/") and os.path.splitext(os.path.basename(name))[0] in GRIDS:
                    grid_given = True
                p = self.resolve(name, d)
                if p and p not in seen:
                    seen.add(p)
                    order.append(p)
                    sub = self.info(p)
                    if sub:
                        queue.append((os.path.dirname(p), sub.includes))
        implicit = ["common.h"]
        if not grid_given:
            implicit.append("grid/quadtree.h")
        for flag in self.server.cfg.get("qccFlags") or []:
            if flag.startswith("-grid="):
                implicit.append("grid/" + flag[6:] + ".h")
        if self.root:
            queue = []
            for name in implicit:
                p = os.path.join(self.root, name)
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
                    p = self.resolve(name, d)
                    if p and p not in seen:
                        seen.add(p)
                        order.append(p)
                        sub = self.info(p)
                        if sub:
                            queue.append((os.path.dirname(p), sub.includes))
        return order

    def header_list(self, extra_dir=None):
        if self.headers is None:
            hs = []
            if self.root:
                for d, dirs, files in os.walk(self.root):
                    rel = os.path.relpath(d, self.root)
                    top = rel.split(os.sep)[0]
                    dirs[:] = sorted(x for x in dirs if not x.startswith(".")
                                     and not (rel == "." and x in HEADER_SKIP))
                    if top in HEADER_SKIP:
                        continue
                    for f in sorted(files):
                        if f.endswith(".h"):
                            p = os.path.join(d, f)
                            hs.append((os.path.normpath(os.path.join(rel, f)), p))
            self.headers = hs
        out = list(self.headers)
        if extra_dir and os.path.isdir(extra_dir) and extra_dir != self.root:
            for f in sorted(os.listdir(extra_dir)):
                if f.endswith(".h"):
                    out.insert(0, (f, os.path.join(extra_dir, f)))
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


def run_qcc(server, files, main, idir, procs=None, key=None):
    """Runs `qcc -fsyntax-only main` in a temporary directory holding
    `files` ({name: (text, real path or None)}), with -I`idir`.

    Returns (raw, None) where raw is a list of diagnostics
    [real path or reported name, line, col, sev, msg, ctx], or
    (None, error message) / (None, None) if superseded."""
    qcc = server.cfg.get("qcc") or "qcc"
    if not shutil.which(qcc):
        return None, "qcc not found (set the `qcc` option or add it to PATH)"
    flags = list(server.cfg.get("qccFlags") or [])
    tmp = tempfile.mkdtemp(prefix="basilisk-lsp-")
    idirs = [idir] + [f[2:] for f in flags if f.startswith("-I") and len(f) > 2]
    if server.basilisk:
        idirs.append(server.basilisk)

    def real(f):
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

    try:
        for name, (text, _) in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                f.write(text)
        env = dict(os.environ)
        if server.basilisk:
            env.setdefault("BASILISK", server.basilisk)
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
        if p.returncode is not None and p.returncode < 0:
            return None, None   # killed (superseded)
        raw, ctx, last = [], None, None
        for l in out.splitlines():
            m = CTX_RE.match(l)
            if m:
                ctx = m.group("fn")
                last = None
                continue
            m = DIAG_RE.match(l)
            if m:
                last = [real(m.group("file")), int(m.group("line")),
                        int(m.group("col")) if m.group("col") else None,
                        m.group("sev"), m.group("msg"), ctx]
                raw.append(last)
                continue
            if (l.startswith("In file included") or re.match(r"^\s+from ", l)
                    or re.match(r"^[^:]+: At top level:", l)
                    or re.match(r"^\s*\d*\s*\|", l) or l.startswith("compilation terminated")):
                last = None
                continue
            if last is not None and l.strip():
                last[4] += "\n" + l   # continuation (e.g. qcc parse error snippets)
        return raw, None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


WRAPPER = "_basilisk_lsp_check.c"
MAX_FOREIGN = 10   # max. diagnostics reported in other files, per check


def find_context(server, path, docs):
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
        if fi and target in {os.path.realpath(f) for f in server.index.closure(p, fi)}:
            if text is None:
                with open(p, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            return p, text
    return None


def check(server, path, text, docs=None, procs=None, key=None):
    """Diagnostics for `path` (with contents `text`).
    Returns (diagnostics, error) — diagnostics None means 'keep the old ones'."""
    path = os.path.abspath(path)
    d, base = os.path.dirname(path), os.path.basename(path)
    if not path.endswith(".h"):
        raw, err = run_qcc(server, {base: (text, os.path.realpath(path))}, base, d, procs, key)
        return (None, err) if raw is None else (make_diagnostics(server, path, text, raw), None)

    # Headers are not compiled on their own by qcc: check them through
    # a .c file which includes them.
    ctx = find_context(server, path, docs or {})
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
        raw, err = run_qcc(server, {cbase: (ctext, os.path.realpath(cpath))}, cbase,
                           os.path.dirname(cpath), procs, key)
        if raw is None:
            return None, err
        target = os.path.realpath(path)
        raw = [r for r in raw if r[0] == target]
        return make_diagnostics(server, path, text, raw, foreign=False), None

    files = {base: (text, os.path.realpath(path)),
             WRAPPER: (f'#include "{base}"\n', None)}
    raw, err = run_qcc(server, files, WRAPPER, d, procs, key)
    if raw is None:
        return None, err
    diags = make_diagnostics(server, path, text, raw, foreign=False)
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


def make_diagnostics(server, path, text, raw, foreign=True):
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

    def rng(l0, c0, l1, c1):
        return {"start": {"line": l0, "character": c0}, "end": {"line": l1, "character": c1}}

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
                c = col - 1
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
            if server.basilisk and f.startswith(server.basilisk):
                rel = os.path.relpath(f, server.basilisk)
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
    def __init__(self):
        self.cfg = dict(DEFAULTS)
        self.docs = {}
        self.out_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.timers = {}
        self.procs = {}
        self.snippets = False
        self.resolve_store = {}
        self.basilisk = None
        self.index = Index(self)
        self.running = True
        self.warned = False
        self.set_config({})

    # -- configuration
    def set_config(self, opts):
        if isinstance(opts, dict):
            if "basilisk" in opts and isinstance(opts["basilisk"], dict):
                opts = opts["basilisk"]
            for k in DEFAULTS:
                if k in opts and opts[k] is not None:
                    self.cfg[k] = opts[k]
        if isinstance(self.cfg.get("qccFlags"), str):
            self.cfg["qccFlags"] = self.cfg["qccFlags"].split()
        self.basilisk = self.find_basilisk()
        self.index.headers = None

    def find_basilisk(self):
        for c in (self.cfg.get("basilisk"), os.environ.get("BASILISK")):
            if c and os.path.isfile(os.path.join(c, "common.h")):
                return os.path.abspath(c)
        q = shutil.which(self.cfg.get("qcc") or "qcc")
        if q:
            d = os.path.dirname(os.path.realpath(q))
            if os.path.isfile(os.path.join(d, "common.h")):
                return d
        return None

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
        log("BASILISK =", self.basilisk)
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
        if not self.basilisk:
            self.notify("window/showMessage", {"type": 2, "message":
                "basilisk-lsp: cannot find Basilisk; set $BASILISK or the `basilisk` option."})

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
        if self.cfg.get("diagnostics") == "onChange":
            self.schedule(uri, float(self.cfg.get("debounce") or 1.0))

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
        if self.cfg.get("diagnostics") == "off":
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
            if err and not self.warned:
                self.warned = True
                self.notify("window/showMessage", {"type": 2, "message": "basilisk-lsp: " + err})
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
        key = doc.get("version")
        cache = doc.get("_ctx")
        if cache and cache[0] == key:
            return cache[1]
        fi = scan(doc["text"], path)
        files = self.index.closure(path, fi)
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
        doc["_ctx"] = (key, ctx)
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
        return self.index.resolve(m.group(2).strip(), os.path.dirname(path))

    def relname(self, path, uri=None):
        if self.basilisk and path.startswith(self.basilisk + os.sep):
            return os.path.relpath(path, self.basilisk)
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
            out.append({"uri": u, "range": {
                "start": {"line": s.line, "character": s.col},
                "end": {"line": s.line, "character": s.col + len(s.name)}}})
        return out or None

    def on_textDocument_documentSymbol(self, p):
        uri = p["textDocument"]["uri"]
        fi, _, _ = self.context(uri)
        out = []
        for s in fi.symbols:
            name = s.name if s.kind != "event" else "event " + s.name
            out.append({"name": name, "kind": SK.get(s.kind, 13), "detail": s.sig,
                        "location": {"uri": uri, "range": {
                            "start": {"line": s.line, "character": 0},
                            "end": {"line": s.line, "character": len(s.name) + s.col}}}})
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
            for rel, absp in self.index.header_list(d):
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
            self.resolve_store[k] = ("sym", s.name)
            item(s.name, s.kind, s.sig, "0", k)
        for name, (kind, sig, _) in BUILTINS.items():
            k = str(len(self.resolve_store))
            self.resolve_store[k] = ("sym", name)
            item(name, kind, sig, "1", k, SNIPPETS.get(name))
        for name in SNIPPETS:
            item(name, "snippet", "", "1", None, SNIPPETS[name])
        for name, syms in table.items():
            s = syms[0]
            if s.path == path:
                continue
            k = str(len(self.resolve_store))
            self.resolve_store[k] = ("sym", name)
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
        name = entry[1]
        uri = None
        for u, d in self.docs.items():
            if d.get("_ctx"):
                uri = u
        syms = []
        if uri:
            syms = self.context(uri)[2].get(name, [])
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
    server = Server()
    if flags:
        server.cfg["qccFlags"] = flags
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    diags, err = check(server, path, text)
    if diags is None:
        print(f"{path}:1:1: error: {err}")
        return 2
    names = {1: "error", 2: "warning", 3: "note"}
    for d in diags:
        s = d["range"]["start"]
        msg = d["message"].replace("\n", " ")
        print(f"{path}:{s['line'] + 1}:{s['character'] + 1}: {names[d['severity']]}: {msg}")
    return 1 if any(d["severity"] == 1 for d in diags) else 0


def main(argv):
    if "--version" in argv:
        print("basilisk-lsp", VERSION)
        return 0
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
