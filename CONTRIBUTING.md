# Contributing

Thanks for helping. Bug reports, editor reports ("the Helix configuration works for me"), and changes are all welcome.

## Ground rules

- **The language server uses only Python's standard library and supports Python 3.8.** It runs on clusters and locked-down machines; don't add dependencies.
- **Language knowledge lives in `spec/language.json`.** That covers keywords, built-ins and their documentation, and Basilisk file detection. Edit it, then run `python3 tools/generate.py`. Never edit a `GENERATED … END GENERATED` block by hand; CI fails if the generated files are out of date.
- **Every change comes with a test** (see below), and the README is updated when behaviour or configuration changes.
- **Versions:** the version number lives in `server/basilisk_lsp.py`, `vscode/package.json` and `basilisk-editor.el`, and CI checks that they agree.

## Layout

| Path | What |
|---|---|
| `server/basilisk_lsp.py` | the language server, `--lint` (used by nano and vim's `:make`) and `--config` |
| `bin/basilisk-lsp` | portable launcher (POSIX sh) |
| `plugin/ ftdetect/ syntax/ ftplugin/ indent/ compiler/` | vim/neovim plugin (the repository root is the plugin) |
| `ale_linters/basilisk/` | ALE linter definition |
| `basilisk-editor.el` | Emacs package |
| `nano/basilisk.nanorc` | nano syntax and linter |
| `vscode/` | VS Code extension (`build.sh` builds the `.vsix` locally) |
| `editors/` | configuration files for Helix, Sublime Text, Kate, coc.nvim |
| `spec/language.json`, `tools/generate.py` | single source of language knowledge, and its generator |
| `tests/` | test suite; `tests/fixtures/` holds the test cases |
| `.github/workflows/` | CI (`ci.yml`) and releases (`release.yml`) |

## Tests

```sh
python3 -m unittest discover -s tests                         # everything available here
BASILISK_LSP_SLOW=1 python3 -m unittest discover -s tests     # also lint all of src/examples
cd tests/vscode && npm ci && npm test                         # VS Code grammar
```

Tests that need Basilisk or a given editor skip themselves when it's missing.

**Run the full suite before pushing if you have Basilisk installed.** GitHub's CI can't download Basilisk (basilisk.fr refuses its servers), so these tests run only on contributors' machines:
- the end-to-end protocol test (`test_lsp.py`);
- qcc errors in each editor;
- the corpus tests.

What's in each file:

| File | Tests | Needs |
|---|---|---|
| `test_scan.py` | the symbol scanner | – |
| `test_config.py` | settings, project file, finding Basilisk, columns, launcher | – |
| `test_diagnostics.py` | the whole checking path, replaying recorded qcc runs | – |
| `test_generate.py` | generated files up to date; detection regexps agree in vim, JavaScript and Emacs | vim, node, emacs (optional) |
| `test_snippets.py` | `editors/` files and the ALE linter | vim (optional) |
| `test_editors.py` | vim, neovim, Emacs and nano, headless with an empty `$HOME` | the editors; qcc for the error checks |
| `test_lsp.py` | end-to-end protocol test | Basilisk |
| `test_corpus.py` | Basilisk's sources and examples | Basilisk |

**Diagnostics fixtures.** `tests/fixtures/diagnostics/<case>/` holds a source file, `scenario.json`, the recorded qcc runs (`qcc.json`) and the expected diagnostics (`expected.json`). To add a case:
1. Create a new directory with the source file and a `scenario.json` (`{"file": "case.c"}`).
2. Run `python3 tests/record_fixtures.py <case>` (needs Basilisk).
3. Review `expected.json` by hand: it becomes the reference.

Re-record everything when qcc's messages change; `git diff tests/fixtures` shows what changed.

## Releases

1. Bump the version in the three places above and update `CHANGELOG.md`.
2. Push a `vX.Y.Z` tag. The release workflow builds the `.vsix` with the official packager and attaches it to a GitHub release.
3. Marketplace publishing runs once the `VSCE_PAT`/`OVSX_PAT` secrets exist.

## How this project is developed

Most of the code is written with the help of Claude, Anthropic's AI assistant, under the direction and review of the maintainer. Contributions written by hand or with other tools are equally welcome. The same rules apply to all of them: tests, review, and a clear description of what changed and why.
