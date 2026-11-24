/**
# Sample

Some *emph* and `code` and $x^2$. */
#include "navier-stokes/centered.h"
face vector av[];
event init (t = 0; t <= end) {
  foreach(reduction(+:s))
    u.x[] = Delta;
}
