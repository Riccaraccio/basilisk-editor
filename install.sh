#!/bin/sh
# Optional installer for Basilisk C editor support.
#
#   ./install.sh [bin] [vim] [nvim] [nano] [vscode]     (no argument = all)
#
# vim/neovim users with a plugin manager don't need this: install the
# repository as a plugin (see README.md). Uses symlinks, so updating the
# repository updates the installation.
set -e
R=$(cd "$(dirname "$0")" && pwd)
targets=${*:-"bin vim nvim nano vscode"}

link_bin() {
  mkdir -p "$HOME/.local/bin"
  ln -sfn "$R/bin/basilisk-lsp" "$HOME/.local/bin/basilisk-lsp"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) echo "bin:    ~/.local/bin/basilisk-lsp" ;;
    *) echo "bin:    ~/.local/bin/basilisk-lsp  (warning: ~/.local/bin is not in PATH)" ;;
  esac
}

for t in $targets; do
  case $t in
    bin) link_bin ;;
    vim)
      d=$HOME/.vim/pack/basilisk/start
      mkdir -p "$d"
      [ -L "$d/basilisk" ] && rm "$d/basilisk"      # link from the old vim/ layout
      ln -sfn "$R" "$d/basilisk-editor"
      echo "vim:    $d/basilisk-editor" ;;
    nvim)
      if [ -d "${XDG_DATA_HOME:-$HOME/.local/share}/nvim/lazy" ]; then
        echo "nvim:   lazy.nvim detected (it ignores pack/ directories); add this plugin spec instead:"
        echo "          { dir = \"$R\" }      -- or { \"Riccaraccio/basilisk-editor\" }"
      else
        d=${XDG_DATA_HOME:-$HOME/.local/share}/nvim/site/pack/basilisk/start
        mkdir -p "$d"
        [ -L "$d/basilisk" ] && rm "$d/basilisk"
        ln -sfn "$R" "$d/basilisk-editor"
        echo "nvim:   $d/basilisk-editor"
      fi ;;
    nano)
      link_bin   # nano's linter runs `basilisk-lsp` from PATH
      line="include \"$R/nano/basilisk.nanorc\""
      touch "$HOME/.nanorc"
      grep -qxF "$line" "$HOME/.nanorc" || echo "$line" >> "$HOME/.nanorc"
      echo "nano:   include line in ~/.nanorc" ;;
    vscode)
      code=""
      for c in code codium cursor; do
        if command -v "$c" >/dev/null; then code=$c; break; fi
      done
      if [ -z "$code" ]; then echo "vscode: no code/codium/cursor command found, skipped"; continue; fi
      "$R/vscode/build.sh" >/dev/null
      "$code" --install-extension "$R"/vscode/basilisk-c-*.vsix --force >/dev/null
      echo "vscode: installed basilisk-c extension ($code)" ;;
    *) echo "unknown target: $t (expected bin, vim, nvim, nano or vscode)" >&2; exit 1 ;;
  esac
done
