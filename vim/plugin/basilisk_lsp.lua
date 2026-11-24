-- Neovim (>= 0.11): enable the Basilisk C language server for filetype=basilisk.
if vim.g.loaded_basilisk_lsp or not (vim.lsp and vim.lsp.config) then
  return
end
vim.g.loaded_basilisk_lsp = true

local cmd = vim.g.basilisk_lsp_cmd or { 'basilisk-lsp' }
if vim.fn.executable(cmd[1]) == 0 then
  return
end
vim.lsp.config('basilisk', {
  cmd = cmd,
  filetypes = { 'basilisk' },
  root_markers = { 'Makefile', '.git', '_darcs' },
  init_options = vim.g.basilisk_lsp_options or {},
})
vim.lsp.enable('basilisk')
