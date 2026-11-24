#include "navier-stokes/centered.h"
scalar s[];
int main() { run(); }
event init (t = 0) {
  foreach()
    s[] = undefined_var + x
  foreach_face()
    uf.x[] = 1.;
}
event foo (i++) {
  double a = s[1,,0];
}
