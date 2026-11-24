/** Needs two-phase.h before it (uses f): can't be checked on its own,
and no .c file in this directory includes it. */
event properties (i++) {
  foreach()
    f[] = clamp (f[], 0., 1.);
}
