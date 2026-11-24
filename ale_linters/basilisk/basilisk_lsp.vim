" ALE (https://github.com/dense-analysis/ale): Basilisk C language server.
" ALE loads this file itself for filetype=basilisk; nothing to configure.
" Options: g:basilisk_lsp_cmd (command list), g:basilisk_lsp_options.

let s:root = get(g:, 'basilisk_lsp_root', expand('<sfile>:p:h:h:h'))

function! s:Executable(buffer) abort
  return get(g:, 'basilisk_lsp_cmd', [s:root . '/bin/basilisk-lsp'])[0]
endfunction

function! s:ProjectRoot(buffer) abort
  " the directory holding .basilisk-lsp.json, else the file's directory
  let l:conf = findfile('.basilisk-lsp.json', fnamemodify(bufname(a:buffer), ':p:h') . ';')
  return l:conf isnot# '' ? fnamemodify(l:conf, ':p:h') : fnamemodify(bufname(a:buffer), ':p:h')
endfunction

call ale#linter#Define('basilisk', {
\   'name': 'basilisk_lsp',
\   'lsp': 'stdio',
\   'executable': function('s:Executable'),
\   'command': '%e',
\   'project_root': function('s:ProjectRoot'),
\   'initialization_options': {b -> get(g:, 'basilisk_lsp_options', {})},
\})
