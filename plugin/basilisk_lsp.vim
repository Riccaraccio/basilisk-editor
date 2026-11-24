" Basilisk C: registers the language server with vim-lsp (if installed) and
" sets qcc as :make program. The server ships with this plugin.
if exists('g:loaded_basilisk_lsp_vim')
  finish
endif
let g:loaded_basilisk_lsp_vim = 1

let g:basilisk_lsp_root = expand('<sfile>:p:h:h')
let s:cmd = get(g:, 'basilisk_lsp_cmd', [g:basilisk_lsp_root . '/bin/basilisk-lsp'])

augroup basilisk_lsp
  autocmd!
  autocmd User lsp_setup if !has('nvim') | call lsp#register_server({
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
