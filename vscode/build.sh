#!/bin/sh
# Builds basilisk-c-<version>.vsix; install it with:  code --install-extension basilisk-c-*.vsix
set -e
cd "$(dirname "$0")"
mkdir -p server
cp ../server/basilisk_lsp.py server/
npm install --omit=dev --no-audit --no-fund
python3 package_vsix.py
