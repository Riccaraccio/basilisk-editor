" Compiler: qcc syntax check via `basilisk-lsp --lint`
if exists('current_compiler')
  finish
endif
let current_compiler = 'basilisk'
if exists(':CompilerSet') != 2
  command -nargs=* CompilerSet setlocal <args>
endif
CompilerSet makeprg=basilisk-lsp\ --lint\ %:S
CompilerSet errorformat=%f:%l:%c:\ %trror:\ %m,%f:%l:%c:\ %tarning:\ %m,%f:%l:%c:\ %tote:\ %m
