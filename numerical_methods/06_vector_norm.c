#include <math.h>
#include <stdio.h>
#include <stdlib.h>

/* Return the Euclidean norm of an array. */
static double num_norm(const double x[], size_t n) {
    double sumsq = 0.0; size_t i;
    for (i = 0; i < n; ++i) sumsq += x[i] * x[i];
    return sqrt(sumsq);
}

/* Test num_norm. */
int main(void) {
    const double x[] = {3, 4};
    printf("norm = %.8f\n", num_norm(x, 2));
    return EXIT_SUCCESS;
}
