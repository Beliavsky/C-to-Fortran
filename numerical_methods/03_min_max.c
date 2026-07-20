#include <math.h>
#include <stdio.h>
#include <stdlib.h>

/* Return the minimum value in an array. */
static double num_min(const double x[], size_t n) {
    double value; size_t i;
    if (n == 0) return NAN;
    value = x[0];
    for (i = 1; i < n; ++i) if (x[i] < value) value = x[i];
    return value;
}

/* Return the maximum value in an array. */
static double num_max(const double x[], size_t n) {
    double value; size_t i;
    if (n == 0) return NAN;
    value = x[0];
    for (i = 1; i < n; ++i) if (x[i] > value) value = x[i];
    return value;
}

/* Test num_min and num_max. */
int main(void) {
    const double x[] = {4, -2, 8, 3, 1};
    size_t n = sizeof(x) / sizeof(x[0]);
    printf("min = %.8f\n", num_min(x, n));
    printf("max = %.8f\n", num_max(x, n));
    return EXIT_SUCCESS;
}
