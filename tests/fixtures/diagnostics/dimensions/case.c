#include "navier-stokes/centered.h"
int main() { run(); }
/** Dimensional analysis: a velocity can't be a length. */
event init (t = 0) {
  foreach()
    u.x[] = x;
}
