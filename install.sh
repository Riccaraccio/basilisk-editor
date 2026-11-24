#!/bin/sh
# Installs Basilisk C editor support.  Usage: ./install.sh [bin] [vim] [nvim] [nano] [vscode]
# (no arguments = all of them). Uses symlinks, so `git pull`/edits take effect immediately.
set -e
R=$(cd "$(dirname "$0")" && pwd)
targets=${*:-"bin vim nvim nano vscode"}
for t in $targets; do
  case $t in
    bin)
      mkdir -p "$HOME/.local/bin"
      ln -sfn "$R/bin/basilisk-lsp" "$HOME/.local/bin/basilisk-lsp"
      echo "bin:    ~/.local/bin/basilisk-lsp (make sure ~/.local/bin is in PATH)" ;;
    vim)
      mkdir -p "$HOME/.vim/pack/basilisk/start"
      ln -sfn "$R/vim" "$HOME/.vim/pack/basilisk/start/basilisk"
      echo "vim:    ~/.vim/pack/basilisk/start/basilisk" ;;
    nvim)
      d=${XDG_DATA_HOME:-$HOME/.local/share}/nvim/site/pack/basilisk/start
      mkdir -p "$d"; ln -sfn "$R/vim" "$d/basilisk"
      echo "nvim:   $d/basilisk" ;;
    nano)
      line="include \"$R/nano/basilisk.nanorc\""
      touch "$HOME/.nanorc"
      grep -qxF "$line" "$HOME/.nanorc" || echo "$line" >> "$HOME/.nanorc"
      echo "nano:   added include to ~/.nanorc" ;;
    vscode)
      command -v code >/dev/null || { echo "vscode: 'code' not found, skipped"; continue; }
      "$R/vscode/build.sh" >/dev/null
      code --install-extension "$R"/vscode/basilisk-c-*.vsix --force
      echo "vscode: installed basilisk-c extension" ;;
    *) echo "unknown target: $t" >&2; exit 1 ;;
  esac
done
