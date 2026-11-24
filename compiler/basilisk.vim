" Compiler: qcc syntax check via `basilisk-lsp --lint` (shipped with this plugin)
if exists('current_compiler')
  finish
endif
let current_compiler = 'basilisk'
if exists(':CompilerSet') != 2
  command -nargs=* CompilerSet setlocal <args>
endif
let s:lsp = get(g:, 'basilisk_lsp_cmd', [expand('<sfile>:p:h:h') . '/bin/basilisk-lsp'])[0]
execute 'CompilerSet makeprg=' . escape(shellescape(s:lsp), ' \|"') . '\ --lint\ %:S'
CompilerSet errorformat=%f:%l:%c:\ %trror:\ %m,%f:%l:%c:\ %tarning:\ %m,%f:%l:%c:\ %tote:\ %m
