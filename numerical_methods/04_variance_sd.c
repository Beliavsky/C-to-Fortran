#include <math.h>
#include <stdio.h>
#include <stdlib.h>

/* Return the sample variance of an array. */
static double num_variance(const double x[], size_t n) {
    double mean = 0.0, sumsq = 0.0; size_t i;
    if (n < 2) return NAN;
    for (i = 0; i < n; ++i) mean += x[i];
    mean /= n;
    for (i = 0; i < n; ++i) { double d = x[i] - mean; sumsq += d * d; }
    return sumsq / (n - 1);
}

/* Return the sample standard deviation of an array. */
static double num_sd(const double x[], size_t n) { return sqrt(num_variance(x, n)); }

/* Test sample variance and standard deviation. */
int main(void) {
    const double x[] = {1, 2, 3, 4, 5};
    size_t n = sizeof(x) / sizeof(x[0]);
    printf("variance = %.8f\n", num_variance(x, n));
    printf("sd       = %.8f\n", num_sd(x, n));
    return EXIT_SUCCESS;
}
