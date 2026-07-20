#include <stdio.h>
#include <stdlib.h>

/* Return the dot product of two arrays. */
static double num_dot(const double x[], const double y[], size_t n) {
    double result = 0.0; size_t i;
    for (i = 0; i < n; ++i) result += x[i] * y[i];
    return result;
}

/* Test num_dot. */
int main(void) {
    const double x[] = {1, 2, 3};
    const double y[] = {4, 5, 6};
    printf("dot = %.8f\n", num_dot(x, y, 3));
    return EXIT_SUCCESS;
}
