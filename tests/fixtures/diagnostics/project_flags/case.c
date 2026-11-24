#include "navier-stokes/centered.h"
#if dimension != 3
#error "this case is 3D: .basilisk-lsp.json must pass -grid=octree"
#endif
int main() { run(); }
