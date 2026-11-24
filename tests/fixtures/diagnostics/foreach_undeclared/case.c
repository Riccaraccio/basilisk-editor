#include "navier-stokes/centered.h"

int main() { run(); }

/** gcc reports this error inside grid/stencils.h (the expanded foreach):
the server must move it back here, on `undefined_var`. */
event init (t = 0) {
  foreach()
    u.x[] = x < 0.5 ? undefined_var : 0.;
}
