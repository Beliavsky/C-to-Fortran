#include <stdio.h>
#include <stdlib.h>

/* Fill an array with equally spaced values. */
static int num_linspace(double start, double end, size_t n, double result[]) {
    double step; size_t i;
    if (n == 0 || result == NULL) return 0;
    if (n == 1) { result[0] = start; return 1; }
    step = (end - start) / (n - 1);
    for (i = 0; i < n; ++i) result[i] = start + i * step;
    result[n - 1] = end;
    return 1;
}

/* Test num_linspace. */
int main(void) {
    double x[6]; size_t i;
    if (!num_linspace(0, 1, 6, x)) return EXIT_FAILURE;
    for (i = 0; i < 6; ++i) printf("%zu %.8f\n", i, x[i]);
    return EXIT_SUCCESS;
}
