" Vim syntax file
" Language: Basilisk C (http://basilisk.fr) -- a superset of C

if exists('b:current_syntax')
  finish
endif

runtime! syntax/c.vim
unlet! b:current_syntax

" Loops, events, reductions
syn match   basiliskRepeat    "\<foreach\%(_\w\+\)\=\>"
syn keyword basiliskStatement event reduction
syn match   basiliskEventName "\%(^event\s\+\)\@<=\w\+"
syn match   basiliskEventCond "\%(^event\s.*\)\@<=\<\%(first\|last\|end\)\>"

" Types and qualifiers
syn keyword basiliskType      scalar vector tensor coord Point
syn keyword basiliskStorage   face vertex symmetric trace macro
syn keyword basiliskOperator  new delete
syn match   basiliskStorage   "(const)"

" Built-in variables, boundaries, boundary conditions
syn keyword basiliskBuiltin   Delta point level dimension
syn keyword basiliskConstant  left right top bottom front back nodata
syn keyword basiliskFunction  dirichlet neumann dirichlet_homogeneous neumann_homogeneous periodic val fine coarse neighbor

" Stencil accesses s[] and components .x .y .z .n .t
syn match   basiliskStencil   "\[\]"
syn match   basiliskComponent "\%(\w\|\]\)\@<=\.[xyznt]\>"

" Literate documentation comments /** ... */ (markdown)
syn region  basiliskDoc start="/\*\*\%(/\)\@!" end="\*/" keepend extend
      \ contains=basiliskDocHeading,basiliskDocEmph,basiliskDocStrong,basiliskDocCode,basiliskDocMath,basiliskDocLink,basiliskDocFence,cTodo,@Spell
syn match   basiliskDocHeading "^\s*#\+\s.*$" contained
syn match   basiliskDocStrong  "\*\*[^*]\+\*\*" contained
syn match   basiliskDocEmph    "\%(^\|[^*]\)\zs\*[^* \t][^*]*\*" contained
syn match   basiliskDocCode    "`[^`]\+`" contained
syn match   basiliskDocMath    "\$\$\=[^$]\+\$\$\=" contained
syn match   basiliskDocLink    "\[[^]]\+\]([^)]\+)" contained
syn region  basiliskDocFence   start="^\s*\%(\~\~\~\|```\).*$" end="^\s*\%(\~\~\~\|```\)\s*$\|\ze\*/" contained

syn sync fromstart

hi def link basiliskRepeat     Repeat
hi def link basiliskStatement  Statement
hi def link basiliskEventCond  Constant
hi def link basiliskEventName  Function
hi def link basiliskType       Type
hi def link basiliskStorage    StorageClass
hi def link basiliskOperator   Operator
hi def link basiliskBuiltin    Identifier
hi def link basiliskConstant   Constant
hi def link basiliskFunction   Function
hi def link basiliskStencil    Special
hi def link basiliskComponent  Identifier
hi def link basiliskDoc        Comment
hi def link basiliskDocHeading Title
hi def link basiliskDocStrong  Bold
hi def link basiliskDocEmph    Italic
hi def link basiliskDocCode    String
hi def link basiliskDocMath    Special
hi def link basiliskDocLink    Underlined
hi def link basiliskDocFence   String
hi def Bold   term=bold cterm=bold gui=bold
hi def Italic term=italic cterm=italic gui=italic

let b:current_syntax = 'basilisk'
