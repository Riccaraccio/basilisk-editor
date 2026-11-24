-- Neovim (>= 0.11): enable the Basilisk C language server for filetype=basilisk.
-- The server ships with this plugin; nothing needs to be on PATH except python3.
if vim.g.loaded_basilisk_lsp or not (vim.lsp and vim.lsp.config) then
  return
end
vim.g.loaded_basilisk_lsp = true

local root = vim.fn.fnamemodify(debug.getinfo(1, 'S').source:sub(2), ':p:h:h')
local cmd = vim.g.basilisk_lsp_cmd or { root .. '/bin/basilisk-lsp' }

vim.lsp.config('basilisk', {
  cmd = cmd,
  filetypes = { 'basilisk' },
  root_markers = { '.basilisk-lsp.json', 'Makefile', '.git', '_darcs' },
  init_options = vim.g.basilisk_lsp_options or {},
  settings = { basilisk = vim.g.basilisk_lsp_options or {} },
})
vim.lsp.enable('basilisk')
