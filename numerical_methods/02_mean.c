#include <math.h>
#include <stdio.h>
#include <stdlib.h>

/* Return the arithmetic mean of an array. */
static double num_mean(const double x[], size_t n) {
    double sum = 0.0;
    size_t i;
    if (n == 0) return NAN;
    for (i = 0; i < n; ++i) sum += x[i];
    return sum / n;
}

/* Test num_mean. */
int main(void) {
    const double x[] = {1, 2, 3, 4, 5};
    size_t n = sizeof(x) / sizeof(x[0]);
    printf("mean = %.8f\n", num_mean(x, n));
    return EXIT_SUCCESS;
}
