" Registers basilisk-lsp with vim-lsp, if installed. (Neovim: see basilisk_lsp.lua)
if exists('g:loaded_basilisk_lsp_vim')
  finish
endif
let g:loaded_basilisk_lsp_vim = 1

let s:cmd = get(g:, 'basilisk_lsp_cmd', ['basilisk-lsp'])

augroup basilisk_lsp
  autocmd!
  autocmd User lsp_setup if !has('nvim') && executable(s:cmd[0]) | call lsp#register_server({
        \ 'name': 'basilisk-lsp',
        \ 'cmd': {server_info -> s:cmd},
        \ 'allowlist': ['basilisk'],
        \ 'initialization_options': get(g:, 'basilisk_lsp_options', {}),
        \ }) | endif
augroup END

" qcc as :make program even when `filetype plugin on` is not set
augroup basilisk_compiler
  autocmd!
  autocmd FileType basilisk if &l:makeprg !~# 'basilisk-lsp' | compiler basilisk | endif
augroup END
