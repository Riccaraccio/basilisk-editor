# Basilisk C for VS Code

Support for [Basilisk C](http://basilisk.fr) source files:

- highlighting of Basilisk constructs (foreach loops, events, fields, built-ins) and of the literate `/** markdown */` comments;
- qcc errors as you type;
- completion, hover documentation from Basilisk's headers, go to definition, and an outline of events and functions.

Basilisk `.c`/`.h` files are recognised by their content; plain C files are left alone. To switch a file by hand, run *Basilisk: Treat this file as Basilisk C*.

**Requirements:** Python ≥ 3.8 and Basilisk (`qcc`). On Windows, use VS Code with WSL. Per-project settings, such as `-grid=octree`, go in a `.basilisk-lsp.json` file.

> This extension is mostly developed with the help of Claude, Anthropic's AI assistant, under the direction and review of its maintainer.

Documentation, other editors and issues: https://github.com/Riccaraccio/basilisk-editor
