" Basilisk C filetype plugin: C settings + qcc as compiler.
if exists('b:did_ftplugin')
  finish
endif
runtime! ftplugin/c.vim ftplugin/c_*.vim ftplugin/c/*.vim
let b:did_ftplugin = 1

setlocal commentstring=//\ %s
" :make checks the file with qcc (quickfix list), :lmake for the location list
compiler basilisk

let b:undo_ftplugin = get(b:, 'undo_ftplugin', '') . '| setlocal commentstring< makeprg< errorformat<'
