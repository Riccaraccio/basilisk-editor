# Plan: making Basilisk editor support shareable

Review date: 2026-11-24. Covers the state of the project at the first git commit.

## Goal

Anyone using Basilisk should be able to install this in their editor with **one documented step**. That should hold whatever their plugin manager or dotfiles look like, and without editing files in this repository. Settings that belong to a project, such as qcc flags or include directories, should be written **once, in the project**, not repeated in each editor's configuration.

In practice that means:

- vim and neovim users install from the repository URL with any plugin manager (lazy.nvim, vim-plug, packer, native `pack/`), and it works with no other setup.
- VS Code users install a ready-made `.vsix`, or the extension from a marketplace, without needing npm or a build.
- Nano, Emacs, Helix, Zed and other editors are covered by short, tested configuration snippets.
- The only things a user needs are `python3` (3.8 or later) and a working Basilisk install (`qcc`).

## Where things stand

**Works and is tested** on WSL2/Ubuntu 24.04 with Python 3.12, vim 9.1, neovim 0.13-dev, nano 7.2 and VS Code 1.147:

- **Language server** (`server/basilisk_lsp.py`, Python standard library only):
  - qcc diagnostics, including the three ways headers are checked (in context, on their own, or not self-contained)
  - completion, hover documentation, go-to-definition and document outline
- **Highlighting** for vim/neovim, nano and VS Code, plus nano's linter hook.
- **Robustness:**
  - The symbol scanner handled all 810 `.c`/`.h` files in Basilisk's `src/` in 0.8 s with no crashes.
  - None of the 39 examples in `src/examples` gets a false diagnostic.
  - The server's syntax parses as Python 3.6+ (checked with `ast.parse(feature_version=…)`). It has not been *run* on anything older than 3.12.

## Review findings

### A. Blockers for sharing

| # | Finding | Effect on a new user |
|---|---|---|
| A1 | **No license.** The VS Code manifest says "SEE LICENSE IN README", and the README names none. | Nobody can legally reuse or redistribute it. |
| A2 | **The vim runtime files live in `vim/`**, not at the repository root. | Plugin managers install the repository root, so `Plug 'x/basilisk-editor'` or a lazy.nvim spec loads nothing. We hit this ourselves: lazy.nvim needed a hand-written `dir = …/vim` spec. `install.sh nvim` does nothing for lazy.nvim users, because lazy.nvim resets `packpath`. |
| A3 | **The server is only found through `PATH`** (`basilisk-lsp`). | vim, neovim and nano integrations silently do nothing unless `install.sh bin` was run *and* `~/.local/bin` is on `PATH`. |
| A4 | **Settings live only in editor configuration** (`basilisk.qccFlags` in VS Code, `vim.g.basilisk_lsp_options` in neovim). | Per-case settings such as `-grid=octree` must be duplicated in every editor and can't be committed with the case. Nano and `--lint` can't receive settings at all. |
| A5 | **Finding Basilisk relies on `$BASILISK`, or `qcc` on `PATH`.** | Editors started from a desktop or GUI often don't inherit the shell environment. Diagnostics then fail with a single, easily missed notice. |
| A6 | **The VS Code extension must be built from source** (npm plus a custom packager). Its publisher ID is `local`. | Most VS Code users won't build it. It can't be published as it is. |

### B. Bugs found in review

| # | Finding | Where |
|---|---|---|
| B1 | `completionItem/resolve` picks the document context from *whichever open document was cached last*. With several files open, completion items can show documentation from the wrong file's includes. | `on_completionItem_resolve` |
| B2 | The symbol context is cached per document *version* only, so a header edited on disk (or the include closure changing) isn't seen until the document itself changes. | `Server.context` |
| B3 | The list of `#include` completions is cached for the life of the server, so newly added headers never appear. | `Index.header_list` |
| B4 | gcc reports byte columns, but LSP positions are UTF-16. Ranges are shifted on lines containing non-ASCII characters (e.g. `ρ` in comments before code). | `make_diagnostics` |
| B5 | `bin/basilisk-lsp` uses `readlink -f`, which is missing on macOS before 12.3. | `bin/basilisk-lsp` |
| B6 | The setting for the Basilisk path is called `basilisk.basilisk` in VS Code: confusing, and costly to rename after the first release. | `vscode/package.json`, server `DEFAULTS` |
| B7 | *Found during Phase 1.* Errors qcc prints without a location (e.g. `qcc: error: cannot parse input (missing closing braces?)`) were dropped, so a file qcc can't parse at all looked clean. | `run_qcc` |

### C. Maintainability: the same knowledge copied in several places

- **Language keywords and built-ins** are listed separately in four files: `vim/syntax/basilisk.vim`, `nano/basilisk.nanorc`, `vscode/syntaxes/basilisk-injection.tmLanguage.json` and the server's `BUILTINS`. Adding a new `foreach_*` loop means four edits, which will drift apart.
- **Basilisk file detection** (the regex plus a hard-coded list of Basilisk header names) exists three times: `ftdetect/basilisk.vim`, `vscode/extension.js` and `basilisk-editor.el` (added after the review).
- **The version number** is in two places: `server/basilisk_lsp.py` and `vscode/package.json`.
- **The VS Code extension carries a copy of the server**, copied in by `build.sh`. A stale copy is easy to ship by mistake.

### D. Testing gaps

- Only the end-to-end protocol test (`tests/test_lsp.py`) is in the repository. The vim, neovim, VS Code grammar, nano and header-checking checks were one-off scripts and weren't saved.
- There is no CI. Every test that needs `qcc` also needs a built Basilisk.
- Only one platform has been tried (WSL/Ubuntu). macOS, other Linux distributions, older Python versions and the stable neovim release are all untested.

### E. Documentation and defaults

- The README predates header checking and doesn't mention the lazy.nvim problem.
- **Emacs** isn't covered, even though Basilisk ships its own `basilisk-mode.el` and Emacs is common among Basilisk users. It just needs an eglot/lsp-mode snippet. **Helix, Zed, Sublime Text and Kate** also only need snippets.
- There is no troubleshooting section ("qcc not found", "BASILISK not set", "wrong grid", "errors in headers").
- The `onChange` default runs qcc (about 2 s of CPU) after every pause in typing. That could be unwelcome on shared cluster login nodes.

## Decisions

| # | Decision | Status |
|---|---|---|
| D1 | License | **Decided: GPL-3.0-or-later**, Basilisk's license. `LICENSE` is a copy of Basilisk's `src/COPYING` (GPLv3). |
| D2 | Hosting | **Decided and done:** public GitHub repository, https://github.com/Riccaraccio/basilisk-editor |
| D3 | Name and IDs | **Postponed:** there is no publisher ID yet. Until there is one, the `.vsix` is distributed as a release download; marketplace publishing (part of Phase 3, step 6) waits. The repository name stays `basilisk-editor`. |
| D4 | Default diagnostics mode | **Decided: `onChange`** (check while typing), changed from `onSave` on 2026-11-24 at the maintainer's request. `onSave` stays available for busy shared machines (project file or editor settings). |
| D6 | Basilisk for CI | **Open.** basilisk.fr refuses GitHub's runners. Options: (a) keep a copy of the official tarball as a release asset of this repository (GPL allows it; refreshed by hand) and point the `BASILISK_TARBALL_URL` repository variable at it; (b) keep qcc tests local only; (c) ask basilisk.fr's admins to allow GitHub's runners. Recommendation: (a). |
| D5 | Upstream | Open. Once it has had a beta, consider proposing it to Basilisk's maintainers (a link from basilisk.fr, or shipping it next to `basilisk-mode.el`). |

## The plan

Each phase ends in a state that could be shared. Phases 1–3 are needed before announcing it; 4–5 make the announcement land well; 6 is feature work afterwards.

### Phase 0: repository foundation *(done)*

- `git init`, `LICENSE` (GPLv3, D1), `.gitignore` (node_modules, built `.vsix`, the server copy inside `vscode/`, `__pycache__`), and this plan.

### Phase 1: install from the repository URL in every editor *(fixes A2–A6, B1–B7; done)*

1. **Move the vim runtime directories to the repository root**: `ftdetect/ syntax/ ftplugin/ indent/ compiler/ plugin/`. The repository then *is* a vim/neovim plugin:
   ```vim
   Plug 'Riccaraccio/basilisk-editor'      " vim-plug
   ```
   ```lua
   { "Riccaraccio/basilisk-editor" }      -- lazy.nvim
   ```
2. **The server locates itself.** The vim and neovim plugins default to `<plugin root>/bin/basilisk-lsp` when `basilisk-lsp` isn't on `PATH`, so no `install.sh` is needed for them. `install.sh` remains only for nano's linter and for a global `basilisk-lsp` command.
3. **Project configuration file.** The server looks for `.basilisk-lsp.json`, starting in the source file's directory and walking up. It is read by every editor *and* by `--lint` (so nano gets it too). Precedence: built-in defaults < editor settings < project file. Example:
   ```json
   { "qccFlags": ["-Wall", "-grid=octree"], "includeDirs": ["../common"], "diagnostics": "onSave" }
   ```
4. **Find Basilisk reliably.** Check, in order: the project file, the editor setting, `$BASILISK`, `qcc` on `PATH`, then common locations (`~/basilisk/src`, `/usr/local/basilisk/src`). If nothing works, show one actionable message naming everything that was tried and how to fix it.
5. **Fix B1–B6:**
   - B1: store the document URI with each completion item.
   - B2: key the context cache on the document version *and* the modification times of the included headers.
   - B3: rescan the header list when a directory's modification time changes.
   - B4: convert byte columns to UTF-16.
   - B5: a portable `bin/basilisk-lsp` without `readlink -f`.
   - B6: rename the setting to `basilisk.path` (`basiliskPath` in the server).
6. **One version number** in the server, which `vscode/package.json` is checked against in CI.
7. **Apply decision D4**: the default diagnostics mode (originally `onSave`; switched to `onChange` during Phase 2).

**Done when:** a fresh user account with only `python3` and Basilisk can:
- in vim and neovim (vim-plug, lazy.nvim and native `pack/`), get highlighting, diagnostics and completion using **only** the plugin-manager line;
- in nano, add one `include` line and get highlighting and the linter;
- in VS Code, install the `.vsix` and get everything;
- put `-grid=octree` in `.basilisk-lsp.json` and have it honoured by **all** of the above.

**Status (2026-11-24): done.** Verified with an empty `$HOME`, no `$BASILISK`, and neither `qcc` nor `basilisk-lsp` on `PATH`:
- vim with a native package: Basilisk filetype and syntax; `:make` runs the bundled launcher and fills the quickfix list.
- neovim with a native package: the server attaches, diagnostics arrive on open, and hover works.
- nano after `install.sh nano`: highlighting, and the linter via the `~/.local/bin` link.
- the project file: a case guarded by `#if dimension != 3 / #error` passes with `-grid=octree` in `.basilisk-lsp.json` and fails without it.
- discovery failure gives a message listing everything tried; bad project files are reported.
- your own lazy.nvim and vim setups work with the new layout.
- no false diagnostics on `src/examples` (0/39), and the header cases are unchanged.

New tests: `tests/test_config.py` (9 unit tests: precedence, project files, discovery, columns) and, in `tests/test_lsp.py`, B1, the onSave default, and onChange via settings.

**Still open:**
- vim-plug installing *from the GitHub URL* (the sandbox here blocks downloading and running plugin managers). **lazy.nvim from the URL is verified** (2026-11-24): `{ "Riccaraccio/basilisk-editor" }` cloned commit b280615 from GitHub and loads it on startup. Native packages cloned from the URL are verified too.
- The VS Code extension has been rebuilt and installed but not yet watched running in the editor.
- The version check runs when the `.vsix` is built; making CI run it belongs to Phase 3.

### Phase 2: one source for language knowledge *(fixes C; done)*

1. `spec/language.json` becomes the single list of keywords, loops, types, qualifiers, built-in variables and functions, boundary names, and their hover documentation. It also holds the file-detection markers.
2. `tools/generate.py` writes the generated parts of: the vim syntax file, the nano rc, the VS Code injection grammar, the Emacs font-lock keywords, the server's `BUILTINS`, and the three detection regexes (vim ftdetect, `extension.js` and `basilisk-editor.el`). Generated blocks are fenced with `GENERATED … END GENERATED` markers.
3. CI fails if the generated files are out of date (`tools/generate.py --check`).

**Done when:** adding a new `foreach_*` loop takes one edit plus `generate.py`.

**Status (2026-11-24): done.**
- `spec/language.json` holds the highlight word lists, the detection rules, and the 52 built-in docs and 10 snippets (extracted from the server, not retyped).
- `tools/generate.py` writes them into six text files and the VS Code grammar.
- Demonstrated: adding one word to the spec and running the generator updated the vim, nano, VS Code and Emacs highlighting; `--check` flagged the stale files first.
- `tests/test_generate.py` checks that the generated files are up to date, and that the three detection regexes (vim, JavaScript, Emacs) agree on 20 sample lines, each in its real engine.
- Editor highlighting re-checked after the switch: vim, nano, VS Code (vscode-textmate) and Emacs.
- Drift it removed:
  - `level` is now highlighted everywhere (VS Code and Emacs lacked it);
  - nano now highlights `nodata`;
  - nano no longer colours `first`/`last` everywhere (it can't restrict them to `event` lines);
  - Emacs/VS Code/vim detection share one header list.
- Also changed: the default diagnostics mode is now `onChange` (see D4).
- CI running `--check` is part of Phase 3.

### Phase 3: tests and CI *(fixes D; done, except qcc tests on GitHub, see status)*

1. **Unit tests that need no qcc:**
   - the scanner, against fixture files;
   - diagnostics mapping, from *recorded* qcc outputs (parse errors, errors gcc reports in headers, header context);
   - configuration precedence;
   - finding Basilisk.
2. **Protocol tests** (the current `tests/test_lsp.py`, extended): headers in each of the three modes, several files open (B1), and the project configuration file.
3. **Editor tests**, all headless:
   - vim: detection, syntax groups, `:make` into the quickfix list;
   - neovim: the server attaches;
   - VS Code grammar: run through `vscode-textmate` with the real C grammar;
   - nano: the rc file parses, and the linter output format is correct.
4. **Corpus test** (only when Basilisk is available): the scanner over all of `src/`, and `--lint` over `src/examples`, with no crashes and no diagnostics.
5. **CI matrix:**
   - Python 3.8 and the latest release;
   - Ubuntu and macOS;
   - stable neovim plus 0.11, and vim 9;
   - one job that builds Basilisk (cached) for the qcc tests.
6. **Release workflow:** on a git tag, build the `.vsix` with the official `vsce` on Node 20 (the Python packager stays as a local fallback), attach it to the GitHub release, and publish to Open VSX and the VS Code Marketplace.

**Done when:** every pull request runs the whole matrix, and a tag produces a published extension.

**Status (2026-11-24):**
- **One command:** `python3 -m unittest discover -s tests` runs 46 tests locally, all passing (3 minutes with `BASILISK_LSP_SLOW=1`). Tests needing Basilisk or an editor skip themselves.
- **Unit tests without qcc:**
  - `test_scan` covers the scanner;
  - `test_config` covers configuration, discovery, columns, and the launcher through symlinks;
  - `test_diagnostics` replays 8 recorded qcc scenarios through the whole checking path: parse errors, an error reported inside an expanded `foreach`, an unparseable file, dimensional analysis, project flags, and the three header modes. A deliberately broken mapping makes 5 of them fail, so they have teeth.
- **Protocol:** `test_lsp` now runs under `unittest`.
- **Editors:** `test_editors` runs vim, neovim, Emacs and nano headless with an empty `$HOME`; `tests/vscode` checks the grammar through `vscode-textmate`.
- **Corpus:** `test_corpus` scans all of Basilisk's sources and lints the examples.
- **CI:** `ci.yml` has three jobs:
  - unit: Python 3.8/3.13, Ubuntu and macOS;
  - editors: neovim 0.11 and stable;
  - full: Basilisk built from the official tarball, cached weekly. A non-blocking step reports when qcc's messages drift from the recorded fixtures.
- **Release:** `release.yml` builds the `.vsix` with the official `vsce` on a `v*` tag and attaches it to a GitHub release. Marketplace publishing is wired but waits for secrets (D3).
- **CI on GitHub: all 7 jobs green** (run 45387659909):
  - unit: Python 3.8 and 3.13, Ubuntu and macOS;
  - editors: neovim 0.11.0 and stable;
  - basilisk;
  - vsix: the official `vsce` builds the extension on every push; the artifact was downloaded and checked to contain the server and `vscode-languageclient`.
- **Found by CI:** on macOS, errors reported in Basilisk headers showed absolute paths when Basilisk is reached through a symlink (`/var` → `/private/var`). Fixed, with a regression test.
- **Open, needs a decision (D6):** basilisk.fr doesn't accept connections from GitHub's runners. TCP connections time out, also over IPv4, while it answers normally elsewhere. So the qcc-dependent tests (end-to-end protocol, qcc diagnostics in each editor, the examples corpus, the fixture drift check) run only locally for now. The Basilisk job warns when that happens. The replayed fixtures still test the diagnostics logic on every push. Building Basilisk itself works (`make ast && make qcc`).

### Phase 4: documentation and more editors *(fixes E)*

1. **README rewrite:**
   - a quick start per editor, one short section each;
   - what's required (python3 and Basilisk);
   - how header checking works;
   - project configuration;
   - troubleshooting.
2. **Tested snippets** for:
   - ~~Emacs~~: done early (2026-11-24) as a package, `basilisk-editor.el`. It provides `basilisk-c-mode` with Basilisk highlighting, content-based detection, eglot (default) or lsp-mode, and `M-x compile`. Tested in batch mode with an empty `$HOME`: detection, faces, eglot diagnostics and hover, and autoloads via `package-vc-install-from-checkout`. lsp-mode isn't tested (not installed here), and markdown highlighting in literate comments is left to Basilisk's `basilisk-mode.el`;
   - Helix (`languages.toml`), Zed, Sublime Text (the LSP package) and Kate;
   - coc.nvim and ALE.
3. `CONTRIBUTING.md` (layout, the generator, running tests), `CHANGELOG.md`, and an issue template that asks for the editor, its version, `basilisk-lsp --version`, `qcc` location and a minimal file.

### Phase 5: beta with real users, then announce

1. Two or three Basilisk users, covering Linux, macOS, WSL and at least one cluster login node. Fix what they find.
2. Tag 0.1.0, publish the extension, announce on the Basilisk mailing list, and contact the maintainers (D5).

### Phase 6: features after release

Discussed in detail earlier; listed here so they aren't lost:

- signature help (cheap);
- semantic tokens: field-aware highlighting, including `u.x` in VS Code (cheap);
- a tree-sitter grammar for Basilisk, which brings local variables, struct members, find-references, and rename that understands `foreach_dimension`. It needs the packaging decision: Python plus the tree-sitter package, Node with WebAssembly, or a Rust binary;
- checking unsaved header edits in context.

## Target layout after phases 1–3

```
basilisk-editor/
├── ftdetect/ syntax/ ftplugin/ indent/ compiler/ plugin/   # vim/neovim plugin (repository root)
├── bin/basilisk-lsp                                       # portable launcher
├── server/basilisk_lsp.py                                 # language server + --lint
├── spec/language.json                                     # single source of language knowledge
├── tools/generate.py                                      # writes the generated syntax/detection blocks
├── nano/basilisk.nanorc
├── vscode/                                                # extension (manifest, client, grammars)
├── editors/                                               # emacs/, helix/, zed/, sublime/, kate/ snippets
├── tests/                                                 # unit, protocol, editor, corpus
├── .github/workflows/                                     # ci.yml, release.yml
├── install.sh                                             # optional: global command, nano include
├── LICENSE  README.md  CONTRIBUTING.md  CHANGELOG.md  PLAN.md
```
