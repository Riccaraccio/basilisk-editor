# Basilisk C editor support

> **Disclaimer:** this project is mostly developed with the help of [Claude](https://claude.ai), Anthropic's AI assistant, under the direction and review of its maintainer. It is tested (see `tests/`), but please report anything that looks wrong.

Editor support for [Basilisk C](http://basilisk.fr) in **vim**, **neovim**, **Emacs**, **nano** and **VS Code**.

| Feature | VS Code | Neovim ≥ 0.11 | Emacs ≥ 29 | Vim | Nano |
|---|---|---|---|---|---|
| Highlighting (foreach, events, fields, `/** markdown */` docs) | ✓ | ✓ | ✓ (no markdown in comments) | ✓ | ✓ |
| qcc errors | ✓ | ✓ | ✓ (eglot/flymake) | with an LSP plugin; `:make` otherwise | `^T ^Y` |
| Completion, hover docs, go to definition, outline | ✓ | ✓ | ✓ (eglot or lsp-mode) | with an LSP plugin | – |

**Requirements:** Python ≥ 3.8 and a working Basilisk install (`qcc`). Nothing else: the language server uses only Python's standard library, and it ships inside the plugin and the extension.

## Install

### Neovim (≥ 0.11) and vim

The repository is a vim/neovim plugin. Install it with your plugin manager:

```lua
{ "Riccaraccio/basilisk-editor" }                 -- lazy.nvim
```
```vim
Plug 'Riccaraccio/basilisk-editor'                " vim-plug
```

With no plugin manager, clone it into a package directory:

```sh
git clone https://github.com/Riccaraccio/basilisk-editor ~/.vim/pack/basilisk/start/basilisk-editor                      # vim
git clone https://github.com/Riccaraccio/basilisk-editor ~/.local/share/nvim/site/pack/basilisk/start/basilisk-editor    # neovim
```

- **Neovim:** the language server is enabled automatically for Basilisk files. Your `LspAttach` keymaps and completion plugin apply to it like any other server.
- **Vim:** there's no built-in LSP client.
  - [vim-lsp](https://github.com/prabirshrestha/vim-lsp) and [ALE](https://github.com/dense-analysis/ale) are configured automatically.
  - [coc.nvim](https://github.com/neoclide/coc.nvim): merge [`editors/coc/coc-settings.json`](editors/coc/coc-settings.json) into yours, with the real path.
  - Without an LSP plugin, `:make` checks the file with qcc and fills the quickfix list (`:copen`).

### Emacs (≥ 29)

```elisp
;; Emacs 30:
(use-package basilisk-editor
  :vc (:url "https://github.com/Riccaraccio/basilisk-editor"))

;; Emacs 29: run once
;;   M-x package-vc-install RET https://github.com/Riccaraccio/basilisk-editor RET

;; Or from a clone:
(add-to-list 'load-path "/path/to/basilisk-editor")
(require 'basilisk-editor)
```

What you get:
- Basilisk `.c`/`.h` files open in `basilisk-c-mode`, which is `c-mode` plus Basilisk keywords.
- The language server starts through **eglot**, built into Emacs 29, which shows qcc errors with flymake. `M-x eldoc` and hover give documentation, and `M-.` goes to definitions.
- `M-x compile` runs the qcc check.

Options (`M-x customize-group RET basilisk`):
- `basilisk-auto-lsp`: `eglot` (default), `lsp-mode` or `nil`.
- `basilisk-lsp-options`: e.g. `(:diagnostics "onSave")`.

Basilisk's own `basilisk-mode.el`, which shows the literate comments as markdown, also works with the language server: run `M-x eglot` in it.

### VS Code (also VSCodium and Cursor)

Build and install the extension with `./install.sh vscode` (needs npm, any Node version). Ready-made `.vsix` files will be attached to the [releases](https://github.com/Riccaraccio/basilisk-editor/releases) from the first release on; install one with `code --install-extension basilisk-c-*.vsix`.

On Windows, use VS Code with WSL, because Basilisk runs in WSL. Install the extension from a WSL terminal so that it runs next to `qcc`.

### Nano

```sh
./install.sh nano
```

This adds an `include` line to `~/.nanorc` and links `basilisk-lsp` into `~/.local/bin`, which must be on your `PATH`. In nano, press `^T` then `^Y` to check the file; `^Y` and `^V` step through the messages.

### Other editors

Any editor with an LSP client can use the server: it is `bin/basilisk-lsp`, speaking LSP over stdio. These editors can't recognise Basilisk files by content, so the configurations attach the server to **C files**. That's best done per project, so your other C files keep clangd.

| Editor | Configuration | Status |
|---|---|---|
| [Helix](https://helix-editor.com) | Copy [`editors/helix/languages.toml`](editors/helix/languages.toml) to `.helix/languages.toml` in your project. Needs `./install.sh bin`. | untested |
| [Sublime Text](https://www.sublimetext.com) (with the [LSP](https://lsp.sublimetext.io) package) | [`editors/sublime/LanguageServers.sublime-settings`](editors/sublime/LanguageServers.sublime-settings) in `Packages/User`; to replace clangd in a project, [`basilisk.sublime-project`](editors/sublime/basilisk.sublime-project). | untested |
| [Kate](https://kate-editor.org) | *Settings → LSP Client → User Server Settings*: [`editors/kate/lspclient-settings.json`](editors/kate/lspclient-settings.json). This applies to all C files. Needs `./install.sh bin`. | untested |
| coc.nvim | [`editors/coc/coc-settings.json`](editors/coc/coc-settings.json) | untested |
| ALE | automatic (`ale_linters/basilisk/`) | tested against a stand-in for ALE's API, not ALE itself |
| Zed | not supported yet: Zed needs an extension to add a language server | – |

"Untested" means written from the editor's documentation and checked for syntax and structure (`tests/test_snippets.py`), but not yet tried in the editor. If you use one of these, please [report](https://github.com/Riccaraccio/basilisk-editor/issues) whether it works.

## Configuration

Settings live in **one file per project**, `.basilisk-lsp.json`, and every editor (and `basilisk-lsp --lint`) reads it. The server looks for it in the source file's directory, then in each parent directory, and uses the first one it finds. So a single file at the top of a directory of cases covers all of them, and a case can override it with its own.

```json
{
  "qccFlags": ["-Wall", "-grid=octree"],
  "includeDirs": ["../common"],
  "diagnostics": "onSave"
}
```

| Setting | Default | |
|---|---|---|
| `qccFlags` | `["-Wall"]` | qcc flags used for checking, e.g. `-grid=octree`, `-DMY_OPTION`, `-I../include` |
| `includeDirs` | `[]` | extra include directories, also used for completion and go-to-definition |
| `diagnostics` | `"onChange"` | `"onChange"` (check while typing), `"onSave"` or `"off"`. Each check costs about 2 s of CPU, so `"onSave"` is kinder to busy shared machines. |
| `debounce` | `1.0` | seconds to wait after typing before checking, with `onChange` |
| `basiliskPath` | auto | Basilisk's `src/` directory; see below |
| `qcc` | `qcc` | qcc executable |

Relative paths in the project file are relative to the file itself.

The same settings can also be given in the editor, where the project file takes precedence:
- **neovim:** `vim.g.basilisk_lsp_options = { diagnostics = "onSave" }`
- **vim-lsp:** `g:basilisk_lsp_options`
- **VS Code:** `basilisk.*` settings, with `basilisk.path` for `basiliskPath`
- **Emacs:** `basilisk-lsp-options`, e.g. `(:diagnostics "onSave")`

**Finding Basilisk.** The server tries, in order: `basiliskPath`, then `$BASILISK`, then the directory of `qcc` on `PATH`, then common locations (`~/basilisk/src`, `~/basilisk/basilisk/src`, `/usr/local/basilisk/src`, `/opt/basilisk/src`). qcc doesn't have to be on `PATH` if it is in that directory. Editors started from a desktop menu often don't see your shell's `$BASILISK`; set `basiliskPath` if Basilisk isn't found.

To see the settings that apply to a file, and any problem with them, run:

```sh
bin/basilisk-lsp --config path/to/case.c
```

## How files are recognised

Basilisk sources are ordinary `.c`/`.h` files, so vim, Emacs and VS Code recognise them by their content: an `event`, a `foreach`, a `scalar s[]` declaration, or a Basilisk `#include`. Plain C files keep C mode. To override:

- **vim/neovim:** `:set ft=basilisk`
- **Emacs:** `M-x basilisk-c-mode`
- **VS Code:** run *Basilisk: Treat this file as Basilisk C*
- **nano:** nano can't look at file contents, so it uses the Basilisk syntax for every `.c`/`.h` file. Since Basilisk C is a superset of C, plain C files still look right.

## How checking works

- **`.c` files:** the buffer is copied to a temporary directory and checked with `qcc -fsyntax-only`.
  - gcc sometimes reports errors inside code that qcc generated from `foreach` bodies; those point at `grid/stencils.h`. They are moved back to the matching identifier in your file and tagged `[reported in …]`.
  - Errors without a location, such as `cannot parse input (missing closing braces?)`, are shown on the first line.
- **Headers** can't be compiled on their own by qcc, so they are checked:
  1. **in context**, through a `.c` file that includes them: an open one, or one in the same directory. Only errors located in the header are shown, when you save it;
  2. otherwise **on their own**, through a one-line wrapper `.c`;
  3. if that fails too, the header probably needs other headers included before it (e.g. `navier-stokes/conserving.h`). A single note explains this instead of a list of spurious errors.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "cannot find Basilisk (tried: …)" | Set `basiliskPath` in `.basilisk-lsp.json`, or set `$BASILISK` for the editor. |
| Errors only in 3D cases (or other grids) | Add `-grid=octree` (etc.) to `qccFlags`, or `#include "grid/octree.h"` in the case. |
| Checking slows down a shared machine | Set `"diagnostics": "onSave"` (or `"off"`). |
| A header shows a single "does not compile on its own" note | Open, or create in the same directory, a `.c` file that includes it. |
| Lazy.nvim: nothing happens | Use the plugin spec above; `pack/` directories are ignored by lazy.nvim. |

## Development

AI coding agents: see [AGENTS.md](AGENTS.md). Everyone else: see [CONTRIBUTING.md](CONTRIBUTING.md): the layout, the ground rules, how to run the tests (with Basilisk installed, run the full suite before pushing), how to add a diagnostics case, and how to release. Changes are listed in [CHANGELOG.md](CHANGELOG.md), and the roadmap is in [PLAN.md](PLAN.md).

In short: to add or change a keyword, built-in or its documentation, edit `spec/language.json` and run `python3 tools/generate.py`. Run the tests with `python3 -m unittest discover -s tests`.

## License

GNU General Public License, version 3 or later: the same license as Basilisk. See [LICENSE](LICENSE).
