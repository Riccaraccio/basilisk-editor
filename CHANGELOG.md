# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

First version, to be released as 0.1.0.

### Language server (`bin/basilisk-lsp`)
- Diagnostics from `qcc -fsyntax-only`, on the unsaved buffer, while typing (`onChange`, default), on save, or off.
  - Errors gcc reports inside code expanded from `foreach` bodies are moved back to the user's line.
  - Errors without a location (e.g. `cannot parse input`) are shown on the first line.
  - A failing qcc is never reported as a clean file.
- Headers are checked in context, through a `.c` file that includes them; on their own, through a wrapper; or, when neither is possible, with a single explanatory note.
- Completion (Basilisk keywords and snippets, symbols from the included headers, `#include` paths, `.x`/`.y`/`.z`), hover with the literate `/** */` documentation, go to definition, document symbols.
- Per-project settings in `.basilisk-lsp.json`, read by every editor and by `--lint`.
- Basilisk found from the project file, `$BASILISK`, `qcc` on `PATH`, or common locations; `--config FILE` shows the settings in effect.
- Python 3.8+, standard library only.

### Editors
- **vim/neovim:** the repository is a plugin.
  - Content-based detection of Basilisk `.c`/`.h` files, syntax with highlighted literate comments, and `:make` via qcc.
  - The language server is enabled automatically in neovim ≥ 0.11, vim-lsp and ALE.
- **Emacs ≥ 29:** `basilisk-editor.el`, with `basilisk-c-mode`, content-based detection, eglot (default) or lsp-mode, and `M-x compile`.
- **VS Code (also VSCodium and Cursor):** extension with highlighting, detection, and the language server.
- **nano:** syntax, and the linter (`^T ^Y`).
- **Helix, Sublime Text, Kate, coc.nvim:** configuration files in `editors/` (untested in those editors).

### Project
- `spec/language.json` is the single source of keywords, file detection and built-in documentation, generated into every editor's files by `tools/generate.py`.
- Test suite, with CI on Python 3.8/3.13, Linux and macOS, neovim 0.11/stable, and the official VS Code packager. Release workflow for `v*` tags.

[Unreleased]: https://github.com/Riccaraccio/basilisk-editor/commits/main
