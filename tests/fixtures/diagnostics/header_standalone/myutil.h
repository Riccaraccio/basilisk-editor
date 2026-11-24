/** A self-contained header: checked on its own, through a wrapper .c. */
#include "utils.h"

double total (scalar s)
{
  double sum = 0.;
  foreach (reduction(+:sum))
    sum += dv()*s[];
  return sum;
}
