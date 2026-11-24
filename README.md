# Basilisk C editor support

Editor support for [Basilisk C](http://basilisk.fr) in **vim**, **neovim**, **nano** and **VS Code**.

| Feature | VS Code | Neovim ≥ 0.11 | Vim | Nano |
|---|---|---|---|---|
| Highlighting (foreach, events, fields, `/** markdown */` docs) | ✓ | ✓ | ✓ | ✓ |
| qcc errors | live | live | live with an LSP plugin, `:make` otherwise | `^T ^Y` |
| Completion, hover docs, go to definition, outline | ✓ | ✓ | with an LSP plugin | – |

The editors share one language server, `server/basilisk_lsp.py`. It needs only Python 3 and its standard library, plus `qcc` on `PATH` for diagnostics.

## Install

```sh
./install.sh             # installs bin, vim, nvim, nano and vscode
./install.sh bin nano    # installs only some of them
```

The script symlinks `basilisk-lsp` into `~/.local/bin`, symlinks the vim plugin into `pack/` for vim and neovim, adds an `include` line to `~/.nanorc`, and builds and installs the VS Code `.vsix`. Run it from a WSL terminal so that VS Code installs the extension on the WSL side, where `qcc` lives.

`$BASILISK` (or `qcc` on `PATH`) is used to find the Basilisk headers.

## How files are recognised

Basilisk sources are ordinary `.c`/`.h` files, so they are recognised by their content: an `event`, a `foreach`, a `scalar s[]` declaration, or a Basilisk `#include`. Plain C files keep the C mode. To override:

- vim: `:set ft=basilisk`
- VS Code: *Basilisk: Treat this file as Basilisk C*
- nano: `nano --syntax=basilisk`. Nano itself picks the Basilisk syntax for every `.c`/`.h` file; since it is a superset of C, plain C files still look right.

## Editor notes

**Neovim ≥ 0.11.** Works with no setup: `plugin/basilisk_lsp.lua` calls `vim.lsp.enable('basilisk')`. Options go in `vim.g.basilisk_lsp_options = { qccFlags = {'-Wall', '-grid=octree'} }`.

**Vim** has no built-in LSP client.
- [vim-lsp](https://github.com/prabirshrestha/vim-lsp) is registered automatically.
- [coc.nvim](https://github.com/neoclide/coc.nvim): add to `coc-settings.json`:
  ```json
  "languageserver": { "basilisk": { "command": "basilisk-lsp", "filetypes": ["basilisk"] } }
  ```
- Without a plugin, `:make` checks the file with qcc and fills the quickfix list.

**Nano.** `^T` then `^Y` runs the linter; `^Y`/`^V` step through the messages.

**VS Code.** Settings are under `basilisk.*`: `qccFlags`, `diagnostics` (`onChange`/`onSave`/`off`), `debounce`, `pythonPath` and `basilisk` (the path to `src/`).

## Server options

These are passed as LSP `initializationOptions` or settings.

| Option | Default | |
|---|---|---|
| `qcc` | `qcc` | qcc executable |
| `qccFlags` | `["-Wall"]` | e.g. `-grid=octree`, `-I../include` (also used to resolve includes) |
| `diagnostics` | `onChange` | `onChange`, `onSave` or `off` |
| `debounce` | `1.0` | seconds |
| `basilisk` | `$BASILISK` | Basilisk `src/` directory |

## How it works

- **Diagnostics:** the buffer is copied to a temporary directory and checked with `qcc -fsyntax-only -I<file dir>`. That takes about 2 s per check. gcc sometimes reports errors inside code that qcc generated from `foreach` bodies; those point at `grid/stencils.h`. They are moved back to the matching identifier in your file and tagged `[reported in …]`.
- **Symbols:** the server scans the headers your file includes (transitively), plus `common.h` and the grid, for functions, events, fields, macros and types. The literate `/** … */` comment just before each one is used as its hover documentation.
- **Limitations:** symbols are found with a scanner, not a full parser, so local variables and struct members are not indexed. Completion falls back to the words in the buffer.

## Layout

```
server/basilisk_lsp.py    language server + `--lint` CLI
bin/basilisk-lsp          launcher
vim/                      ftdetect, syntax, ftplugin, indent, compiler, LSP registration (vim + neovim)
nano/basilisk.nanorc
vscode/                   extension (build.sh builds the .vsix, no Node 20 needed)
tests/test_lsp.py         end-to-end protocol test (python3 tests/test_lsp.py)
```

## License

GNU General Public License, version 3 or later — the same license as Basilisk. See [LICENSE](LICENSE).
