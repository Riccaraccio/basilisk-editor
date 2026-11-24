/** Checked in the context of drop.c, which includes it after two-phase.h:
`rho1` is known, `undefined_g` is not. */
event acceleration (i++) {
  face vector av = a;
  foreach_face()
    av.x[] += rho1*undefined_g;
}
