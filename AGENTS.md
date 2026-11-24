# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository. For the full picture, read `README.md`, `CONTRIBUTING.md` and `PLAN.md` (roadmap, decisions D1–D6, the status of each phase).

## What this is

Editor support for [Basilisk C](http://basilisk.fr), a C dialect for fluid dynamics compiled by `qcc`. There is one language server (`server/basilisk_lsp.py`) plus native integrations for vim/neovim, Emacs, VS Code and nano, and configuration files for Helix, Sublime Text, Kate and coc.nvim.

## Commands

```sh
python3 -m unittest discover -s tests                        # all tests (skip what isn't installed)
BASILISK_LSP_SLOW=1 python3 -m unittest discover -s tests    # + lint all of $BASILISK/examples (~3 min)
python3 -m unittest tests.test_diagnostics                   # one file
(cd tests/vscode && npm ci && npm test)                      # VS Code grammar
python3 tools/generate.py            # after editing spec/language.json
python3 tools/generate.py --check    # CI runs this
python3 tests/record_fixtures.py     # re-record qcc outputs (needs Basilisk); then review git diff tests/fixtures
bin/basilisk-lsp --lint FILE.c       # what qcc says, as the server maps it
bin/basilisk-lsp --config FILE.c     # effective settings, where Basilisk/qcc were found
vscode/build.sh                      # build the .vsix locally (works on Node 18)
```

## Rules

- **The server uses only the Python standard library and supports Python 3.8.** No dependencies, no syntax newer than 3.8. In particular, f-string expressions can't contain backslashes before Python 3.12; CI runs 3.8.
- **`spec/language.json` is the single source** of keywords, built-ins and their docs, and Basilisk file detection. Never edit `GENERATED … END GENERATED` blocks, or `vscode/syntaxes/basilisk-injection.tmLanguage.json`'s `keywords` entry, by hand. Edit the spec and run `tools/generate.py`.
- **The version** is in three places, which CI checks: `server/basilisk_lsp.py` (`VERSION`), `vscode/package.json`, and `basilisk-editor.el` (`;; Version:`).
- **Every change gets a test.** Behaviour or configuration changes also update `README.md`, and user-visible changes go in `CHANGELOG.md` (Unreleased).
- **Be honest about what was verified.** Configurations for editors that weren't actually run are labelled "untested" in the README; keep it that way until someone confirms them.
- **The repository root is the vim/neovim plugin** (`plugin/ ftdetect/ syntax/ ftplugin/ indent/ compiler/ ale_linters/`). Don't move these into a subdirectory: plugin managers install the root.
- **Settings precedence:** built-in defaults < editor settings < the project file `.basilisk-lsp.json` (searched upwards from the file). New settings go in `DEFAULTS` in the server, and also in the VS Code `package.json` and the README table.

## Workflow

- Work on a branch, push it, and let CI pass (`gh run watch`) before merging to `main`. Don't push to `main`, tag releases, or change repository settings without the maintainer's go-ahead.
- **If Basilisk is installed, run the full suite before pushing.** GitHub's runners can't reach basilisk.fr (decision D6), so the qcc-dependent tests run only locally: `test_lsp`, the qcc parts of `test_editors`, and `test_corpus`.
- Commit messages: a summary line, a blank line, then what changed and why.
- Don't modify the user's own editor configuration (`~/.config/nvim`, `~/.vimrc`, `~/.nanorc`, VS Code settings) without asking. Tests use an empty temporary `$HOME`.

## Things that are not obvious

- **qcc only translates `.c` files.** A header given directly is compiled as plain C, which gives hundreds of false errors. Headers are checked through a `.c` file that includes them (an open one, or one in the same directory), else through a one-line wrapper, else with one explanatory note. See `check()` in the server.
- **gcc reports errors in code expanded from `foreach` bodies as located in `grid/stencils.h`.** `make_diagnostics` moves them back to the matching identifier in the user's file and tags them `[reported in …]`.
- **Some qcc errors have no location** (`qcc: error: cannot parse input …`). `parse_qcc_output` attaches them to line 1, and a failing qcc whose output wasn't recognised is never reported as a clean file.
- **Paths that qcc/gcc report are resolved with `realpath`.** Compare them against both the configured Basilisk root and its `realpath`: on macOS, `/var` is a symlink to `/private/var`.
- **Diagnostics are tested without qcc** by replaying `tests/fixtures/diagnostics/*/qcc.json` through the hooks `QCC_REPLAY`/`QCC_RECORD`. When qcc's messages change, re-record the fixtures and review `expected.json`.
- **GitHub's runners can't connect to basilisk.fr** (TCP timeouts). Don't add CI steps that download Basilisk.
- **The official `@vscode/vsce` packager needs Node 20.** `vscode/package_vsix.py` builds the `.vsix` with Python where only older Node is available; CI uses `vsce`. The VS Code extension carries a copy of the server, made by `build.sh`.
- **lazy.nvim ignores `pack/` directories**, so its users need a plugin spec (`{ "Riccaraccio/basilisk-editor" }`).
- **Nano** applies the last syntax defined for a file name, so `~/.nanorc` includes ours after the system's. Its linter is `^T ^Y`.
- **Emacs in batch mode:** flymake doesn't start in buffers that aren't displayed; tests call `(flymake-start)` explicitly. cc-mode reads `event init` as a declaration, so the event font-lock rule uses `override`.
- **Vim:** `s:` variables are private to their script, so tests reach detection through `BasiliskDetect()`. Keywords take priority over `syn match`, so the event name is highlighted with a lookbehind match.
- **The maintainer's shell is zsh:** an unquoted `$VAR` holding several words is not split into words.

## About this project's development

The project is mostly developed with Claude (see the README disclaimer), under the maintainer's direction and review. Commits made by an agent end with a `Co-Authored-By:` trailer.
