" Detect Basilisk C (http://basilisk.fr) sources among .c/.h files by content.
" Override per buffer with  :set filetype=basilisk  (or =c).

function! BasiliskDetect() abort
  if exists('g:basilisk_detect') && !g:basilisk_detect
    return
  endif
  let l:pat = '\v^\s*%(event\s+\w+\s*\(|#\s*include\s*"%(navier-stokes|grid|two-phase|vof|'
        \ . 'saint-venant|layered|embed|tension|run|utils|output|view|fractions|axi|'
        \ . 'reduced|curvature|tracer|diffusion|poisson|green-naghdi|compressible|bcg|'
        \ . 'advection|atmosphere|momentum|contact|heights|common)[/.]|'
        \ . '%(%(face|vertex|symmetric)\s+)?%(scalar|vector|tensor)\s+\*?\s*\w+\s*\[\]|'
        \ . 'foreach%(_\w+)?\s*\()'
  for l:line in getline(1, min([line('$'), 500]))
    if l:line =~# l:pat
      set filetype=basilisk
      return
    endif
  endfor
endfunction

autocmd BufRead,BufNewFile *.c,*.h call BasiliskDetect()
